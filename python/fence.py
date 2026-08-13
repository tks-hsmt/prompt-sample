"""dr-fence: 旧 ACTIVE 側（PEER）を閉塞する.

入力:
    {"dry_run": false}       # 省略時 false

出力:
    {"target": "ap-northeast-1", "apigw": {...}, "eventbridge": {...}}

例外:
    RetryableError    -> SFN の Retry
    BestEffortFailed  -> SFN の Catch（ResultPath に記録して後続へ進む）

やらないこと:
    - time.sleep による待機          -> Wait ステート
    - 独自のリトライループ            -> Retry
    - 失敗時の分岐                    -> Catch
    リージョン障害中は PEER のコントロールプレーンが応答しない前提。
    閉塞はベストエフォートであり、失敗してもワークフローは止めない。
"""

from common import account_id, config
from switch_ops import set_apigw, set_eventbridge


def handler(event, context):
    dry_run = bool(event.get("dry_run", False))
    cfg = config("peer")
    account = account_id(context)

    result = {
        "action": "fence",
        "target_region": cfg["region"],
        "dry_run": dry_run,
    }

    # 入口を止める（API GW -> Lambda -> SQS 経路の遮断）
    result["apigw"] = set_apigw(cfg, account, blocked=True, dry_run=dry_run)

    # イベント起動を止める（EventBridge -> Lambda 経路の遮断）
    result["eventbridge"] = set_eventbridge(cfg, enabled=False, dry_run=dry_run)

    # 注: Lambda のイベントソースマッピングは意図的に無効化しない。
    #     既にキューに入ったメッセージは PEER 側で処理させ切る。
    #     入口だけ止めて消費は続けるのが正しいドレインの形。

    return result
