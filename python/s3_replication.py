"""dr-s3-replication: S3 レプリケーションルールの Status を切り替える.

【案 A を採用する場合にのみデプロイする】

    案 A: 平時は逆方向ルールを Disabled にしておき、切替時にこの Lambda で
          Status をトグルする。
    案 B: 双方向を常時 Enabled で固定し、切替時に S3 の操作を一切行わない。
          案 B ならこの Lambda は不要（デプロイしない）。

役割ごとの操作:
    PEER（旧 ACTIVE）… 旧方向のレプリケーションを Disabled にする
    SELF（新 ACTIVE）… 逆方向のレプリケーションを Enabled にする

呼び出し順序（重要）:
    SELF の Enabled 化は、必ず activate（トラフィック開放）より前に実行する。
    ライブレプリケーションの対象は「ルールが Enabled になった後に書かれた
    オブジェクト」だけなので、開放が先だと取りこぼしが発生し、後から
    Batch Replication での追い付きが必要になる。

    推奨フェーズ順:  fence(PEER) -> s3_replication(self,  enable=True)
                     -> check_* -> activate(SELF)

入力:
    {"role": "self" | "peer", "enable": true|false, "dry_run": false}

出力:
    {"action": "s3-replication", "target_region": "...", "role": "...",
     "buckets": {"<bucket>": {...}}}

===========================================================================
必要な IAM 権限（この Lambda のみ）
---------------------------------------------------------------------------
    s3:GetReplicationConfiguration  arn:aws:s3:::<両リージョンのバケット>
    s3:PutReplicationConfiguration  arn:aws:s3:::<両リージョンのバケット>
    iam:PassRole                    レプリケーション用ロールの ARN

    ※ バケットは SSE-S3（AES256）で SSE-C を禁止しているため、KMS 関連の
      権限（kms:Decrypt / kms:Encrypt）や SseKmsEncryptedObjects の設定は不要。
===========================================================================

例外:
    RetryableError    -> SFN の Retry
    BestEffortFailed  -> SFN の Catch（記録して続行）

    SELF 側の失敗も FatalError ではなく BestEffortFailed にしている。
    逆方向レプリケーションを有効化できなくても、新 ACTIVE でのサービス提供
    自体は成立するため、切替全体を止める方が損失が大きいという判断。
    RPO を優先して切替を止めたい場合は role=="self" のとき FatalError に
    変更すること。

既知のリスク（案 A 固有）:
    PutBucketReplication は宛先バケットの存在を検証する。相手リージョンが
    全域障害の最中にこの検証が通るかは公式に明記がなく確定できない。
    案 B（平時に設定済み）ならこの問題は発生しない。
"""

from __future__ import annotations

import logging

from common import (
    AWS_ERRORS,
    BestEffortFailed,
    RegionConfig,
    RetryableError,
    Role,
    client,
    config,
    raise_classified,
)

logger = logging.getLogger(__name__)


def set_replication(cfg: RegionConfig, bucket: str, *,
                    enable: bool, dry_run: bool) -> dict:
    """バケットのレプリケーションルールの Status を一括で切り替える.

    put_bucket_replication は設定を丸ごと置き換えるため、必ず
    get -> 修正 -> put の順で行い、設定を自前で組み立て直さない
    （フィルタ・優先度・宛先などの既存設定を失わないため）。
    """
    s3 = client("s3", cfg.region)
    want = "Enabled" if enable else "Disabled"

    try:
        configuration = s3.get_bucket_replication(
            Bucket=bucket)["ReplicationConfiguration"]

        current = {rule["ID"]: rule["Status"] for rule in configuration["Rules"]}
        if all(status == want for status in current.values()):
            return {"ok": True, "changed": False, "status": want,
                    "reason": "already in desired state", "rules": current}

        if dry_run:
            return {"ok": True, "changed": False, "status": want,
                    "dry_run": True, "rules": current,
                    "would": f"set all rules to {want}"}

        for rule in configuration["Rules"]:
            rule["Status"] = want

        s3.put_bucket_replication(
            Bucket=bucket, ReplicationConfiguration=configuration)

    except AWS_ERRORS as exc:
        raise_classified(exc, role=cfg.role, what=f"s3-replication({bucket})")

    logger.info("s3 replication %s: bucket=%s status=%s rules=%d",
                cfg.region, bucket, want, len(configuration["Rules"]))
    return {"ok": True, "changed": True, "status": want,
            "rules": {rule["ID"]: want for rule in configuration["Rules"]}}


def handler(event: dict, context) -> dict:
    role: Role = event.get("role", "self")
    enable = bool(event["enable"])
    dry_run = bool(event.get("dry_run", False))
    cfg = config(role)

    logger.info("s3-replication start: role=%s region=%s enable=%s dry_run=%s",
                role, cfg.region, enable, dry_run)

    result: dict = {
        "action": "s3-replication",
        "role": role,
        "target_region": cfg.region,
        "enable": enable,
        "dry_run": dry_run,
        "buckets": {},
    }

    # 複数バケットを独立に処理する。1 つ失敗しても残りは必ず試みる
    # （fence と同じ方針）。
    errors: list[str] = []
    retryable = False

    for bucket in cfg.replication_buckets:
        try:
            result["buckets"][bucket] = set_replication(
                cfg, bucket, enable=enable, dry_run=dry_run)
        except RetryableError as exc:
            retryable = True
            result["buckets"][bucket] = {"ok": False, "error": str(exc)}
            errors.append(f"{bucket}: {exc}")
        except BestEffortFailed as exc:
            result["buckets"][bucket] = {"ok": False, "error": str(exc)}
            errors.append(f"{bucket}: {exc}")

    if errors:
        message = "; ".join(errors)
        # 一時エラーが 1 つでもあれば全体を再試行させる。操作は冪等。
        if retryable:
            raise RetryableError(message)
        raise BestEffortFailed(message)

    return result
