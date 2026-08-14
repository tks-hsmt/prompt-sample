"""dr-check-apigw: API Gateway が受けられる状態か確認する.

設定確認だけでは「設定は正しいが通らない」を検出できないため、
ヘルスチェック URL へ実リクエストを 1 回投げる。

必要な IAM:
    apigateway:GET   SELF の /restapis/<id>/stages/<stage>

入力 : {}   出力 : 正常時は無し / 未収束なら RetryableError
"""

from __future__ import annotations

import urllib.error
import urllib.request

from aws import client
from config import ApiGatewayConfig
from handlers import check_handler

HEALTH_TIMEOUT_SEC = 5
HTTP_OK = 200


@check_handler("apigw", ApiGatewayConfig)
def handler(cfg: ApiGatewayConfig) -> dict:
    # aws apigateway get-stage --rest-api-id <id> --stage-name <stage>
    #   の methodSettings."*/*".throttlingRateLimit / throttlingBurstLimit
    apigw = client("apigateway", cfg.region)
    stage = apigw.get_stage(restApiId=cfg.rest_api_id, stageName=cfg.stage)
    settings = stage.get("methodSettings", {}).get("*/*", {})
    throttle = {"rate": settings.get("throttlingRateLimit"),
                "burst": settings.get("throttlingBurstLimit")}

    if not cfg.health_url:
        return {}

    # スキームを検証してから開く。設定ミスで file: 等が渡ることを防ぐ。
    if not cfg.health_url.startswith("https://"):
        raise ValueError(f"SELF_HEALTH_URL must be https: {cfg.health_url}")

    try:
        with urllib.request.urlopen(  # noqa: S310 - スキームは上で検証済み
                cfg.health_url, timeout=HEALTH_TIMEOUT_SEC) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code

    if status != HTTP_OK:
        # スロットリングが 0 のままなら 429 が返る。値も一緒に残す。
        return {"http_status": status, "throttle": throttle}
    return {}
