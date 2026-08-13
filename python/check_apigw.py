"""dr-check-apigw: 新 ACTIVE 側の API Gateway が受けられる状態か確認する.

===========================================================================
必要な IAM 権限（この Lambda のみ）
---------------------------------------------------------------------------
    apigateway:GET   arn:aws:apigateway:<SELF リージョン>::/restapis/<id>/stages/<stage>

    ※ SELF リージョンのみ。観測系なので読み取り専用ロールにできる。
    ※ ヘルスチェック URL への HTTPS リクエストに IAM 権限は不要
      （リソースポリシーで Allow されていれば通る）。
===========================================================================

コントロールプレーンの設定確認だけでは「設定は正しいが通らない」を検出
できないため、保守経路のヘルスチェックパスへ実リクエストを 1 発投げる。
（NE 機器への誤警報にならない経路であること）

入力 : {}
出力 : {"check": "apigw", "region": "...", "ready": bool, "detail": {...}}
"""

from __future__ import annotations

import urllib.error
import urllib.request

from common import RegionConfig, check_result, client, config, guard

HEALTH_TIMEOUT_SEC = 5


def check_apigw(cfg: RegionConfig) -> dict:
    apigw = client("apigateway", cfg.region)
    stage = apigw.get_stage(restApiId=cfg.rest_api_id, stageName=cfg.stage)
    detail = {
        "deployment_id": stage.get("deploymentId"),
        "last_updated": str(stage.get("lastUpdatedDate")),
    }

    if not cfg.health_url:
        return {"ok": True, "http": "skipped (no health_url configured)", **detail}

    try:
        with urllib.request.urlopen(cfg.health_url,
                                    timeout=HEALTH_TIMEOUT_SEC) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code

    return {"ok": status == 200, "http_status": status, **detail}


def handler(event: dict, context) -> dict:
    cfg = config("self")
    return check_result("apigw", cfg.region,
                        {"apigw": guard("apigw", check_apigw, cfg)})
