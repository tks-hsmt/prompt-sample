"""dr-check-apigw: 新 ACTIVE 側の API Gateway が受けられる状態か確認する.

===========================================================================
必要な IAM 権限
---------------------------------------------------------------------------
    apigateway:GET
        arn:aws:apigateway:<SELF>::/restapis/<id>/stages/<stage>

    ※ SELF リージョンのみ。読み取り専用ロールにできる。
    ※ ヘルスチェック URL への HTTPS リクエストに IAM 権限は不要。
===========================================================================

コントロールプレーンの設定確認だけでは「設定は正しいが通らない」を検出
できないため、保守経路のヘルスチェックパスへ実リクエストを 1 発投げる。
（NE 機器への誤警報にならない経路であること）

閉塞はステージのスロットリングで行うため、開放が効いていなければ
429 が返る。失敗時はスロットリングの現在値も結果に含める。

入力 : {}
出力 : 正常時は無し / 未収束なら RetryableError
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
