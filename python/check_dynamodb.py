"""dr-check-dynamodb: 新 ACTIVE 側の DynamoDB テーブルが使える状態か確認する.

===========================================================================
必要な IAM 権限（この Lambda のみ）
---------------------------------------------------------------------------
    dynamodb:DescribeTable   arn:aws:dynamodb:<SELF>:<acct>:table/<対象>

    ※ SELF リージョンのみ。読み取り専用。
===========================================================================

東京・大阪でレプリケーションしない構成のため、PEER の中身は確認不要。
リージョンごとに独立した状態を持ち、大阪は大阪の状態で動き始めればよい。
テーブルが使える状態かだけを見る。

入力 : {}
出力 : {"check": "dynamodb", "region": "...", "ready": bool, "detail": {...}}
"""

from __future__ import annotations

from common import RegionConfig, check_result, client, config, guard


def check_dynamodb(cfg: RegionConfig) -> dict:
    ddb = client("dynamodb", cfg.region)
    tables = {}
    for name in cfg.table_names:
        status = ddb.describe_table(TableName=name)["Table"]["TableStatus"]
        tables[name] = {"status": status, "ok": status == "ACTIVE"}
    return {"ok": all(t["ok"] for t in tables.values()), "tables": tables}


def handler(event: dict, context) -> dict:
    cfg = config("self")
    return check_result("dynamodb", cfg.region,
                        {"dynamodb": guard("dynamodb", check_dynamodb, cfg)})
