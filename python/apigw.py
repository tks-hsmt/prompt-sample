"""dr-apigw: API Gateway の閉塞 / 開放（ステージのスロットリング方式）.

===========================================================================
必要な IAM 権限
---------------------------------------------------------------------------
    apigateway:GET / apigateway:PATCH
        arn:aws:apigateway:<両リージョン>::/restapis/<id>/stages/<stage>

    ※ role を引数で受けるため PEER / SELF 両リージョンの ARN が必要。
    ※ リソースポリシー方式で必要だった apigateway:POST と
      UpdateRestApiPolicy は不要になった。
===========================================================================

【方式】ステージのスロットリングを 0 にして閉塞し、通常値に戻して開放する。

    閉塞: rateLimit=0 / burstLimit=0  -> 全リクエストが 429
    開放: 環境変数（または引数）の値に戻す

リソースポリシーに Deny を入れる方式を採らない理由:

    1. リソースポリシーの更新は再デプロイしないと反映されず、2 手になる
    2. /policy に対する patch は op:replace のみで（op:add / op:remove は
       非サポート）、Statement 単位の更新ができない。既存ポリシーに
       IP 制限などがあると、閉塞のたびに壊す危険がある
    3. 旧アクティブ側の閉塞はリージョン障害中に実行できない可能性があり、
       構造的にベストエフォート。遮断機構だけを「保証された」ものにする
       必然性がない

    スロットリングは公式に「ベストエフォートで適用され、保証された上限では
    なく目標値」とされている。理論上わずかな漏れの可能性は残るが、上記 3 の
    理由から許容する。

【前提】東京・大阪は同一 AWS アカウント。両リージョンのリソースを同じ
実行ロールで操作できることを前提にしている。

【前提】現在ステージには明示的なスロットリング設定が無く、アカウントの
デフォルト値（rate=10000 / burst=5000）が表示されている状態。

    - スロットリング設定は op:remove が非サポートのため、一度書き込むと
      「未設定」には戻せない。ただし復元先がデフォルトと同値なので実害はない
    - 副作用として、明示設定後はアカウントのクォータを引き上げても
      このステージは環境変数の値のままになる。引き上げ時はここも上げる

入力 : {"role": "self"|"peer", "blocked": true|false, "dry_run": false,
        "throttle": {"rate": 10000, "burst": 5000}}   # throttle は任意
出力 : {"action": "apigw", "role": ..., "region": ..., "changed": bool, ...}

例外 : RetryableError   -> Retry
       ContinuableError -> Catch（role=peer の恒久エラー）
       その他           -> 未捕捉 = ワークフロー停止（role=self の恒久エラー）
"""

from __future__ import annotations

from aws import client
from config import RegionConfig
from handlers import ops_handler
from logging_json import get_logger

logger = get_logger(__name__)

# 全リソース・全メソッドに適用するメソッド設定のキー
ALL_METHODS = "*/*"
RATE_PATH = f"/{ALL_METHODS}/throttling/rateLimit"
BURST_PATH = f"/{ALL_METHODS}/throttling/burstLimit"

# 閉塞時の値。burst=0 で全リクエストが 429 になる。
BLOCKED_RATE = 0.0
BLOCKED_BURST = 0


def _current_throttle(stage: dict) -> tuple[float | None, int | None]:
    """ステージの現在のスロットリング値を返す.

    明示設定が無い場合 methodSettings は空になる（アカウントのデフォルトが
    適用されるが、ステージの設定としては存在しない）。その場合は None を返す。
    """
    settings = stage.get("methodSettings", {}).get(ALL_METHODS)
    if not settings:
        return None, None
    return (settings.get("throttlingRateLimit"),
            settings.get("throttlingBurstLimit"))


@ops_handler("apigw")
def handler(cfg: RegionConfig, event: dict, *, dry_run: bool, context) -> dict:
    blocked = bool(event["blocked"])

    if blocked:
        want_rate, want_burst = BLOCKED_RATE, BLOCKED_BURST
    else:
        # 復元値は環境変数が既定。Step Functions の引数で上書きできる。
        override = event.get("throttle") or {}
        want_rate = float(override.get("rate", cfg.throttle_rate))
        want_burst = int(override.get("burst", cfg.throttle_burst))

    apigw = client("apigateway", cfg.region)

    # AWS 例外の捕捉・分類は @ops_handler が担う（正常系だけを書く）
    stage = apigw.get_stage(restApiId=cfg.rest_api_id, stageName=cfg.stage)
    current_rate, current_burst = _current_throttle(stage)

    if (current_rate, current_burst) == (want_rate, want_burst):
        # 既に目標状態（冪等）
        return {"changed": False, "blocked": blocked,
                "rate": want_rate, "burst": want_burst,
                "reason": "already in desired state"}

    if dry_run:
        return {"changed": False, "blocked": blocked,
                "rate": want_rate, "burst": want_burst,
                "current_rate": current_rate, "current_burst": current_burst,
                "would": f"set rate={want_rate} burst={want_burst}"}

    # スロットリングはステージ設定なので再デプロイ不要（1 手で完結）
    apigw.update_stage(
        restApiId=cfg.rest_api_id,
        stageName=cfg.stage,
        patchOperations=[
            {"op": "replace", "path": RATE_PATH, "value": str(want_rate)},
            {"op": "replace", "path": BURST_PATH, "value": str(want_burst)},
        ],
    )
    logger.info("apigw %s: blocked=%s rate=%s->%s burst=%s->%s",
                cfg.region, blocked, current_rate, want_rate,
                current_burst, want_burst)

    return {"changed": True, "blocked": blocked,
            "rate": want_rate, "burst": want_burst,
            "previous_rate": current_rate, "previous_burst": current_burst}
