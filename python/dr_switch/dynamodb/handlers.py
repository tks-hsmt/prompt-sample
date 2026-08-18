"""DynamoDB テーブルが使える状態か確認する.

テーブルが使える状態かだけを見る。

必要な IAM:
    dynamodb:DescribeTable

ハンドラ（成功時は何も返さない。失敗・未収束は例外で表現する）:
    check   入力 {"dry_run": bool}。成功時は何も返さない。未収束は例外で表現する
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from dr_switch.core import NotRecoverableError, client, lambda_handler
from dr_switch.dynamodb.config import DynamoDbConfig

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.literals import TableStatusType

# 待てば ACTIVE になる状態。これ以外は待っても解消しないものとして扱う
#（ARCHIVING は遷移中だが行き先が ARCHIVED なので含めない）。
HEALTHY_STATUS: TableStatusType = "ACTIVE"
TRANSIENT_STATUSES: frozenset[TableStatusType] = frozenset({"CREATING", "UPDATING"})


@lambda_handler("dynamodb-check", DynamoDbConfig)
def check(cfg: DynamoDbConfig, event: dict, *, dry_run: bool, context) -> dict:
    # aws dynamodb describe-table --table-name <n> の Table.TableStatus
    ddb = client("dynamodb", cfg.region)
    problems: dict[str, dict] = {}
    fatal: dict[str, dict] = {}

    for name in cfg.table_names:
        status = ddb.describe_table(TableName=name)["Table"]["TableStatus"]
        if status == HEALTHY_STATUS:
            continue
        target = problems if status in TRANSIENT_STATUSES else fatal
        target[name] = {"status": status}

    if fatal:
        raise NotRecoverableError(
            json.dumps({"dynamodb": fatal}, ensure_ascii=False, default=str))
    return problems
