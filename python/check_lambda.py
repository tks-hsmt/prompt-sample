"""dr-check-lambda: 新 ACTIVE 側の Lambda が実行可能な状態か確認する.

===========================================================================
必要な IAM 権限（この Lambda のみ）
---------------------------------------------------------------------------
    lambda:GetFunction               arn:aws:lambda:<SELF>:<acct>:function:<対象>
    lambda:ListEventSourceMappings   *   （リソースレベル指定不可）

    ※ SELF リージョンのみ。読み取り専用。
===========================================================================

確認内容:
    State == "Active" かつ LastUpdateStatus == "Successful"
    SQS を消費するイベントソースマッピングが Enabled であること

【未確認の前提】SQS の消費が Lambda のイベントソースマッピングである前提。
EKS Pod 側でポーリングしている場合、ESM の確認は無意味になる。

入力 : {}
出力 : {"check": "lambda", "region": "...", "ready": bool, "detail": {...}}
"""

from __future__ import annotations

from common import RegionConfig, check_result, client, config, guard


def check_lambda(cfg: RegionConfig) -> dict:
    lam = client("lambda", cfg.region)
    functions: dict[str, dict] = {}

    for name in cfg.function_names:
        conf = lam.get_function(FunctionName=name)["Configuration"]
        state_ok = (conf.get("State") == "Active"
                    and conf.get("LastUpdateStatus") == "Successful")

        mappings = [
            {"uuid": m["UUID"], "state": m["State"]}
            for m in lam.list_event_source_mappings(
                FunctionName=name).get("EventSourceMappings", [])
        ]
        esm_ok = all(m["state"] == "Enabled" for m in mappings)

        functions[name] = {
            "state": conf.get("State"),
            "last_update": conf.get("LastUpdateStatus"),
            "event_source_mappings": mappings,
            "ok": state_ok and esm_ok,
        }

    return {"ok": all(f["ok"] for f in functions.values()),
            "functions": functions}


def handler(event: dict, context) -> dict:
    cfg = config("self")
    return check_result("lambda", cfg.region,
                        {"lambda": guard("lambda", check_lambda, cfg)})
