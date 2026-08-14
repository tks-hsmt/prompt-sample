"""dr-s3-replication: S3 レプリケーションルールの Status を切り替える.

【案 A を採用する場合にのみデプロイする】

    案 A: 平時は逆方向ルールを Disabled にしておき、切替時にこの Lambda で
          Status をトグルする。
    案 B: 双方向を常時 Enabled で固定し、切替時に S3 の操作を一切行わない。
          案 B ならこの Lambda は不要（デプロイしない）。

===========================================================================
必要な IAM 権限
---------------------------------------------------------------------------
    s3:GetReplicationConfiguration / s3:PutReplicationConfiguration
        arn:aws:s3:::<両リージョンのバケット>
    iam:PassRole
        レプリケーション用ロールの ARN

    ※ バケットは SSE-S3（AES256）で SSE-C を禁止しているため、KMS 関連の
      権限や SseKmsEncryptedObjects の設定は不要。
===========================================================================

呼び出し順序（重要）:
    role=self の Enabled 化は、必ず activate（トラフィック開放）より前に実行する。
    ライブレプリケーションの対象は「ルールが Enabled になった後に書かれた
    オブジェクト」だけなので、開放が先だと取りこぼしが発生し、後から
    Batch Replication での追い付きが必要になる。

既知のリスク（案 A 固有）:
    PutBucketReplication は宛先バケットの存在を検証する。相手リージョンが
    全域障害の最中にこの検証が通るかは公式に明記がなく確定できない。
    案 B（平時に設定済み）ならこの問題は発生しない。

入力 : {"role": "self"|"peer", "enabled": true|false, "dry_run": false}
出力 : {"action": "s3-replication", "buckets": {...}, ...}
"""

from __future__ import annotations

from aws import client
from config import S3Config
from handlers import ops_handler, run_per_item
from logging_json import get_logger

logger = get_logger(__name__)


def _set_replication(cfg: S3Config, bucket: str, *,
                     enabled: bool, dry_run: bool) -> dict:
    """バケットのレプリケーションルールの Status を一括で切り替える.

    put_bucket_replication は設定を丸ごと置き換えるため、必ず
    get -> 修正 -> put の順で行い、設定を自前で組み立て直さない
    （フィルタ・優先度・宛先などの既存設定を失わないため）。

    例外の捕捉は run_per_item が担う（バケット単位で集約するため）。
    """
    s3 = client("s3", cfg.region)
    want = "Enabled" if enabled else "Disabled"

    configuration = s3.get_bucket_replication(
        Bucket=bucket)["ReplicationConfiguration"]
    current = {rule["ID"]: rule["Status"] for rule in configuration["Rules"]}

    if all(status == want for status in current.values()):
        return {"changed": False, "status": want, "rules": current}

    if dry_run:
        return {"changed": False, "status": want, "rules": current,
                "would": f"set all rules to {want}"}

    for rule in configuration["Rules"]:
        rule["Status"] = want
    s3.put_bucket_replication(
        Bucket=bucket, ReplicationConfiguration=configuration)

    return {"changed": True, "status": want,
            "rules": {rule["ID"]: want for rule in configuration["Rules"]}}


@ops_handler("s3-replication", S3Config)
def handler(cfg: S3Config, event: dict, *, dry_run: bool, context) -> dict:
    enabled = bool(event["enabled"])
    buckets = run_per_item(
        cfg.replication_buckets,
        lambda bucket: _set_replication(
            cfg, bucket, enabled=enabled, dry_run=dry_run),
        role=cfg.role, what="s3-replication",
    )
    return {"enabled": enabled, "buckets": buckets}
