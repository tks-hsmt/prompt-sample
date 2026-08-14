"""dr-check-dynamodb: DynamoDB テーブルが使える状態か確認する.

必要な IAM:
    dynamodb:DescribeTable

入力 : {}   出力 : 正常時は無し / 未収束なら RetryableError
"""

from __future__ import annotations

from aws import client
from config import DynamoDbConfig
from handlers import check_handler


@check_handler("dynamodb", DynamoDbConfig)
def handler(cfg: DynamoDbConfig) -> dict:
    # aws dynamodb describe-table --table-name <name> の Table.TableStatus
    ddb = client("dynamodb", cfg.region)
    return {
        name: {"status": status}
        for name in cfg.table_names
        if (status := ddb.describe_table(
            TableName=name)["Table"]["TableStatus"]) != "ACTIVE"
    }
