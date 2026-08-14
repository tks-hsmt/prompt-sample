"""dr-apigw: API Gateway の閉塞 / 開放.

ステージのスロットリングを 0 にして閉塞し、通常値に戻して開放する。
スロットリングはステージ設定なので再デプロイは不要。

必要な IAM:
    apigateway:GET / apigateway:PATCH
        arn:aws:apigateway:<両リージョン>::/restapis/<id>/stages/<stage>

入力 : {"role": "self"|"peer", "blocked": bool, "dry_run": bool,
        "throttle": {"rate": float, "burst": int}}   # throttle は任意
出力 : {"action": "apigw", "changed": bool, "rate": ..., "burst": ...}
"""

from __future__ import annotations

from aws import client
from config import ApiGatewayConfig
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


@ops_handler("apigw", ApiGatewayConfig)
def handler(cfg: ApiGatewayConfig, event: dict, *, dry_run: bool, context) -> dict:
    blocked = bool(event["blocked"])

    if blocked:
        want_rate, want_burst = BLOCKED_RATE, BLOCKED_BURST
    else:
        override = event.get("throttle") or {}
        want_rate = float(override.get("rate", cfg.throttle_rate))
        want_burst = int(override.get("burst", cfg.throttle_burst))

    apigw = client("apigateway", cfg.region)

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

    # aws apigateway update-stage --rest-api-id <id> --stage-name <stage>
    #   --patch-operations op=replace,path=/*/*/throttling/rateLimit,value=<v>
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
