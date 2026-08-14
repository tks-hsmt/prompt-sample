"""dr-s3-replication: S3 レプリケーションルールの Status を切り替える.

S3 案 A（切替時にトグル）を採用する場合のみデプロイする。
role=self の Enabled 化は、開放より前に実行すること（ライブ
レプリケーションの対象は Enabled 後に書かれたオブジェクトだけのため）。

必要な IAM:
    s3:GetReplicationConfiguration / s3:PutReplicationConfiguration
    iam:PassRole  … レプリケーション用ロール

入力 : {"role": "self"|"peer", "enabled": bool, "dry_run": bool}
出力 : {"action": "s3-replication", "buckets": {...}}
"""

from __future__ import annotations

from aws import client
from config import S3Config
from handlers import ops_handler, run_per_item
from logging_json import get_logger

logger = get_logger(__name__)


def _set_replication(cfg: S3Config, bucket: str, *,
                     enabled: bool, dry_run: bool) -> dict:
    """レプリケーションルールの Status を一括で切り替える.

    put_bucket_replication は設定を丸ごと置き換えるため、
    get -> 修正 -> put の順で行う。
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
