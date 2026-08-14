"""dr-check-s3: バケットの到達性とレプリケーション Status を確認する.

必要な IAM:
    s3:ListBucket / s3:GetReplicationConfiguration

入力 : {}   出力 : 正常時は無し / 未収束なら RetryableError
"""

from __future__ import annotations

from botocore.exceptions import ClientError

from aws import client
from config import S3Config
from handlers import check_handler

NOT_CONFIGURED = "ReplicationConfigurationNotFoundError"


@check_handler("s3", S3Config)
def handler(cfg: S3Config) -> dict:
    s3 = client("s3", cfg.region)
    problems: dict[str, dict] = {}

    for bucket in cfg.replication_buckets:
        # aws s3api head-bucket --bucket <b>（アクセス不可なら例外を素通しさせる）
        s3.head_bucket(Bucket=bucket)

        # aws s3api get-bucket-replication --bucket <b>
        #   の ReplicationConfiguration.Rules[].Status
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
