"""Lambda が実行可能な状態か確認する.

State / LastUpdateStatus と、イベントソースマッピングが Enabled かを見る。

必要な IAM:
    lambda:GetFunction / lambda:ListEventSourceMappings

ハンドラ（成功時は何も返さない。失敗・未収束は例外で表現する）:
    check   入力 {"dry_run": bool}。成功時は何も返さない。未収束は例外で表現する
"""

from __future__ import annotations

from dr_switch.core import client, lambda_handler
from dr_switch.lambda_function.config import LambdaConfig


@lambda_handler("lambda-check", LambdaConfig)
def check(cfg: LambdaConfig, event: dict, *, dry_run: bool, context) -> dict:
    lam = client("lambda", cfg.region)
    problems: dict[str, dict] = {}

    for name in cfg.function_names:
        # aws lambda get-function --function-name <name>
        #   の Configuration.State / Configuration.LastUpdateStatus
        conf = lam.get_function(FunctionName=name)["Configuration"]
        issue = {}

        if conf.get("State") != "Active":
            issue["state"] = conf.get("State")
        if conf.get("LastUpdateStatus") != "Successful":
            issue["last_update_status"] = conf.get("LastUpdateStatus")

        # aws lambda list-event-source-mappings --function-name <name>
        #   の EventSourceMappings[].State
        # 既定では 100 件で無言に打ち切られるためページネータを使う
        paginator = lam.get_paginator("list_event_source_mappings")
        disabled = [
            m["UUID"]
            for page in paginator.paginate(FunctionName=name)
            for m in page["EventSourceMappings"]
            if m["State"] != "Enabled"
        ]
        if disabled:
            issue["event_source_mappings_not_enabled"] = disabled

        if issue:
            problems[name] = issue

    return problems
