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

入力 : {}
出力 : 正常時は無し / 未収束なら RetryableError
"""

from __future__ import annotations

import urllib.error
import urllib.request

from common import RegionConfig, check_handler, client

HEALTH_TIMEOUT_SEC = 5


@check_handler("apigw")
def handler(cfg: RegionConfig) -> dict:
    apigw = client("apigateway", cfg.region)
    stage = apigw.get_stage(restApiId=cfg.rest_api_id, stageName=cfg.stage)

    if not cfg.health_url:
        return {}

    try:
        with urllib.request.urlopen(cfg.health_url,
                                    timeout=HEALTH_TIMEOUT_SEC) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code

    if status != 200:
        return {"http_status": status, "deployment_id": stage.get("deploymentId")}
    return {}
