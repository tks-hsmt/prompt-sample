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

# TableStatus の分類。取り得る値は boto3-stubs の TableStatusType（Literal）に
# 対応し、テストで網羅性を検証している。
# ARCHIVING は遷移中だが行き先が ARCHIVED（利用不可）なので停止側。
HEALTHY_STATUSES: frozenset[TableStatusType] = frozenset({"ACTIVE"})
TRANSIENT_STATUSES: frozenset[TableStatusType] = frozenset({"CREATING", "UPDATING"})
FATAL_STATUSES: frozenset[TableStatusType] = frozenset({
    "DELETING", "ARCHIVING", "ARCHIVED",
    "INACCESSIBLE_ENCRYPTION_CREDENTIALS", "REPLICATION_NOT_AUTHORIZED",
})


@lambda_handler("dynamodb-check", DynamoDbConfig)
def check(cfg: DynamoDbConfig, event: dict, *, dry_run: bool, context) -> dict:
    # aws dynamodb describe-table --table-name <n> の Table.TableStatus
    ddb = client("dynamodb", cfg.region)
    problems: dict[str, dict] = {}
    fatal: dict[str, dict] = {}

    for name in cfg.table_names:
        status = ddb.describe_table(TableName=name)["Table"]["TableStatus"]
        if status in HEALTHY_STATUSES:
            continue
        # DELETING / ARCHIVED / INACCESSIBLE_ENCRYPTION_CREDENTIALS は
        # 待っても ACTIVE にならない
        target = problems if status in TRANSIENT_STATUSES else fatal
        target[name] = {"status": status}

    if fatal:
        raise NotRecoverableError(
            json.dumps({"dynamodb": fatal}, ensure_ascii=False, default=str))
    return problems
