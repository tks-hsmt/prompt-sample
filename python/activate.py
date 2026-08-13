"""dr-activate: 新 ACTIVE 側（SELF）を開放する.

入力:
    {"dry_run": false}

出力:
    {"target": "ap-northeast-3", "apigw": {...}, "eventbridge": {...}}

例外:
    RetryableError -> SFN の Retry
    FatalError     -> ワークフロー停止（Catch しない）
    開放できない = 切替が成立しない、なので失敗は致命的として扱う。
    fence（失敗許容）とは扱いが逆になる点が要。

反映ラグ:
    EventBridge の有効化は反映まで短い待ち時間がある。ここでは待たず、
    後続の check_readiness を Wait + Choice でループさせて吸収する。
"""

from common import account_id, config
from switch_ops import set_apigw, set_eventbridge


def handler(event, context):
    dry_run = bool(event.get("dry_run", False))
    cfg = config("self")
    account = account_id(context)

    result = {
        "action": "activate",
        "target_region": cfg["region"],
        "dry_run": dry_run,
    }

    result["eventbridge"] = set_eventbridge(cfg, enabled=True, dry_run=dry_run)
    result["apigw"] = set_apigw(cfg, account, blocked=False, dry_run=dry_run)

    return result
