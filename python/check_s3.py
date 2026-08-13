"""dr-check-s3: 新 ACTIVE 側の S3 バケットとレプリケーション状態を確認する.

===========================================================================
必要な IAM 権限（この Lambda のみ）
---------------------------------------------------------------------------
    s3:ListBucket                   arn:aws:s3:::<SELF リージョンのバケット>
                                    （head_bucket に必要）
    s3:GetReplicationConfiguration  arn:aws:s3:::<SELF リージョンのバケット>

    ※ SELF リージョンのみ。読み取り専用。
    ※ バケットは SSE-S3（AES256）で SSE-C 禁止のため KMS 権限は不要。
===========================================================================

案 A（切替時トグル）では「逆方向が Enabled になったか」の確認になり、
案 B（常時双方向）では「意図せず Disabled になっていないか」の確認になる。
どちらの方式でも意味を持つ。

入力 : {}
出力 : {"check": "s3", "region": "...", "ready": bool, "detail": {...}}
"""

from __future__ import annotations

from common import RegionConfig, check_result, client, config, guard

NOT_CONFIGURED = "ReplicationConfigurationNotFoundError"


def check_s3(cfg: RegionConfig) -> dict:
    s3 = client("s3", cfg.region)
    buckets: dict[str, dict] = {}

    for bucket in cfg.replication_buckets:
        s3.head_bucket(Bucket=bucket)  # アクセス不可なら例外 -> guard が捕捉
        try:
            rules = s3.get_bucket_replication(
                Bucket=bucket)["ReplicationConfiguration"]["Rules"]
            statuses = {rule["ID"]: rule["Status"] for rule in rules}
            ok = all(status == "Enabled" for status in statuses.values())
        except s3.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] != NOT_CONFIGURED:
                raise
            statuses, ok = {}, False

        buckets[bucket] = {"replication_rules": statuses, "ok": ok}

    return {"ok": all(b["ok"] for b in buckets.values()), "buckets": buckets}


def handler(event: dict, context) -> dict:
    cfg = config("self")
    return check_result("s3", cfg.region, {"s3": guard("s3", check_s3, cfg)})
