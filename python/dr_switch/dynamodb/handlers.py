"""DynamoDB テーブルが使える状態か確認する.

テーブルが使える状態かだけを見る。

必要な IAM:
    dynamodb:DescribeTable

ハンドラ:
    check   入力 {}
"""

from __future__ import annotations

from dr_switch.core import check_handler, client
from dr_switch.dynamodb.config import DynamoDbConfig


@check_handler("dynamodb", DynamoDbConfig)
def check(cfg: DynamoDbConfig) -> dict:
    # aws dynamodb describe-table --table-name <n> の Table.TableStatus
    ddb = client("dynamodb", cfg.region)
    return {
        name: {"status": status}
        for name in cfg.table_names
        if (status := ddb.describe_table(
            TableName=name)["Table"]["TableStatus"]) != "ACTIVE"
    }
