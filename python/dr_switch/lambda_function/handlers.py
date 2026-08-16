"""Lambda が呼び出せる状態か確認する.

VPC 設定のある関数は、長くアイドル状態が続くと Lambda が外部リソースを回収し
State が Inactive になる。その状態で呼び出すと最初の 1 回は失敗し、リソースが
再作成されるまで Pending になる。待機側の関数は普段呼ばれないため、切替の
瞬間にこの状態になっている可能性がある。

必要な IAM:
    lambda:GetFunctionConfiguration

ハンドラ（成功時は何も返さない。失敗・未収束は例外で表現する）:
    check   入力 {"dry_run": bool}
"""

from __future__ import annotations

import json

from dr_switch.core import NotRecoverableError, client, lambda_handler
from dr_switch.lambda_function.config import LambdaConfig

# 待てば収束する状態。リソース作成中・デプロイ中で、時間が経てば Active になる。
TRANSIENT_STATES = frozenset({"Pending"})
TRANSIENT_UPDATE_STATUSES = frozenset({"InProgress"})


@lambda_handler("lambda-check", LambdaConfig)
def check(cfg: LambdaConfig, event: dict, *, dry_run: bool, context) -> dict:
    lam = client("lambda", cfg.region)
    problems: dict[str, dict] = {}
    fatal: dict[str, dict] = {}

    for name in cfg.function_names:
        # aws lambda get-function-configuration --function-name <name>
        #   の State / LastUpdateStatus
        # ListFunctions では State を取得できないため関数ごとに呼ぶ
        #（公式に「State 等を得るには GetFunction を使う」と明記がある）。
        conf = lam.get_function_configuration(FunctionName=name)
        state = conf.get("State")
        update = conf.get("LastUpdateStatus")

        issue = {}
        if state != "Active":
            issue["state"] = state
            issue["state_reason"] = conf.get("StateReason")
        if update != "Successful":
            issue["last_update_status"] = update
            issue["last_update_status_reason"] = conf.get("LastUpdateStatusReason")
        if not issue:
            continue

        # Inactive / Failed は待っても解消しない。Inactive の解消には関数の
        # 呼び出しが必要で、状態を見るだけでは何も起きない。
        recoverable = (state in TRANSIENT_STATES
                       or update in TRANSIENT_UPDATE_STATUSES)
        (problems if recoverable else fatal)[name] = issue

    if fatal:
        raise NotRecoverableError(
            json.dumps({"lambda": fatal}, ensure_ascii=False, default=str))
    return problems
