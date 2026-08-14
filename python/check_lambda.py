"""dr-check-lambda: 新 ACTIVE 側の Lambda が実行可能な状態か確認する.

===========================================================================
必要な IAM 権限
---------------------------------------------------------------------------
    lambda:GetFunction              arn:aws:lambda:<SELF>:<acct>:function:<対象>
    lambda:ListEventSourceMappings  *   （リソースレベル指定不可）

    ※ SELF リージョンのみ。読み取り専用。
===========================================================================

確認内容:
    State == "Active" かつ LastUpdateStatus == "Successful"
    SQS を消費するイベントソースマッピングが Enabled であること
    （SQS の消費が Lambda の ESM であることは確認済み）

入力 : {}
出力 : 正常時は無し / 未収束なら RetryableError
"""

from __future__ import annotations

from common import RegionConfig, check_handler, client


@check_handler("lambda")
def handler(cfg: RegionConfig) -> dict:
    lam = client("lambda", cfg.region)
    problems: dict[str, dict] = {}

    for name in cfg.function_names:
        conf = lam.get_function(FunctionName=name)["Configuration"]
        issue = {}

        if conf.get("State") != "Active":
            issue["state"] = conf.get("State")
        if conf.get("LastUpdateStatus") != "Successful":
            issue["last_update_status"] = conf.get("LastUpdateStatus")

        disabled = [
            m["UUID"]
            for m in lam.list_event_source_mappings(
                FunctionName=name).get("EventSourceMappings", [])
            if m["State"] != "Enabled"
        ]
        if disabled:
            issue["event_source_mappings_not_enabled"] = disabled

        if issue:
            problems[name] = issue

    return problems
