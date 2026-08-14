"""dr-check-s3: 新 ACTIVE 側の S3 バケットとレプリケーション状態を確認する.

===========================================================================
必要な IAM 権限
---------------------------------------------------------------------------
    s3:ListBucket                   arn:aws:s3:::<SELF のバケット>
                                    （head_bucket に必要）
    s3:GetReplicationConfiguration  arn:aws:s3:::<SELF のバケット>

    ※ SELF リージョンのみ。読み取り専用。
    ※ バケットは SSE-S3（AES256）で SSE-C 禁止のため KMS 権限は不要。
===========================================================================

案 A（切替時トグル）では「逆方向が Enabled になったか」の確認になり、
案 B（常時双方向）では「意図せず Disabled になっていないか」の確認になる。
どちらの方式でも意味を持つ。

レプリケーション設定が存在しない場合は待っても解消しないが、Step Functions
側では Retry の上限で止まる。設定不備は dry_run の定期実行で平時に検出する。

入力 : {}
出力 : 正常時は無し / 未収束なら RetryableError
"""

from __future__ import annotations

from botocore.exceptions import ClientError

from common import RegionConfig, check_handler, client

NOT_CONFIGURED = "ReplicationConfigurationNotFoundError"


@check_handler("s3")
def handler(cfg: RegionConfig) -> dict:
    s3 = client("s3", cfg.region)
    problems: dict[str, dict] = {}

    for bucket in cfg.replication_buckets:
        s3.head_bucket(Bucket=bucket)  # アクセス不可なら例外を素通しさせる

        try:
            rules = s3.get_bucket_replication(
                Bucket=bucket)["ReplicationConfiguration"]["Rules"]
        except ClientError as exc:
            if exc.response["Error"]["Code"] != NOT_CONFIGURED:
                raise
            problems[bucket] = {"reason": "replication configuration does not exist"}
            continue

        disabled = {rule["ID"]: rule["Status"] for rule in rules
                    if rule["Status"] != "Enabled"}
        if disabled:
            problems[bucket] = {"rules_not_enabled": disabled}

    return problems
