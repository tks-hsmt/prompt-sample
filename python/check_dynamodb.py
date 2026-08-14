"""dr-check-dynamodb: 新 ACTIVE 側の DynamoDB テーブルが使える状態か確認する.

===========================================================================
必要な IAM 権限
---------------------------------------------------------------------------
    dynamodb:DescribeTable   arn:aws:dynamodb:<SELF>:<acct>:table/<対象>

    ※ SELF リージョンのみ。読み取り専用。
===========================================================================

東京・大阪でレプリケーションしない構成のため、PEER の中身は確認不要。
リージョンごとに独立した状態を持ち、大阪は大阪の状態で動き始めればよい。
テーブルが使える状態かだけを見る。

入力 : {}
出力 : 正常時は無し / 未収束なら RetryableError
"""

from __future__ import annotations

from aws import client
from config import DynamoDbConfig
from handlers import check_handler


@check_handler("dynamodb", DynamoDbConfig)
def handler(cfg: DynamoDbConfig) -> dict:
    ddb = client("dynamodb", cfg.region)
    return {
        name: {"status": status}
        for name in cfg.table_names
        if (status := ddb.describe_table(
            TableName=name)["Table"]["TableStatus"]) != "ACTIVE"
    }
