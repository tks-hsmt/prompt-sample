"""DynamoDB テーブルが使える状態か確認する.

テーブルが使える状態かだけを見る。

必要な IAM:
    dynamodb:DescribeTable

ハンドラ（成功時は何も返さない。失敗・未収束は例外で表現する）:
    check   入力 {"dry_run": bool}。成功時は何も返さない。未収束は例外で表現する
"""

from __future__ import annotations

from dr_switch.core import client, lambda_handler
from dr_switch.dynamodb.config import DynamoDbConfig


@lambda_handler("dynamodb-check", DynamoDbConfig)
def check(cfg: DynamoDbConfig, event: dict, *, dry_run: bool, context) -> dict:
    # aws dynamodb describe-table --table-name <n> の Table.TableStatus
    ddb = client("dynamodb", cfg.region)
    return {
        name: {"status": status}
        for name in cfg.table_names
        if (status := ddb.describe_table(
            TableName=name)["Table"]["TableStatus"]) != "ACTIVE"
    }
