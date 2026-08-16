"""API Gateway の閉塞 / 開放 / 確認.

ステージのスロットリングを 0 にして閉塞し、通常値に戻して開放する。
スロットリングはステージ設定なので再デプロイは不要。

必要な IAM（自関数が対象とするリージョンの ARN のみ）:
    apigateway:GET / apigateway:PATCH
        arn:aws:apigateway:<リージョン>::/restapis/<id>/stages/<stage>

ハンドラ（成功時は何も返さない。失敗・未収束は例外で表現する）:
    block   閉塞。入力 {"dry_run": bool}
    enable  開放。入力 {"dry_run": bool,
            "throttle": {"rate": float, "burst": int}}  # throttle は任意
    check   開放が効いているか確認。入力 {}
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request

from dr_switch.apigateway.config import ApiGatewayConfig
from dr_switch.core import client, lambda_handler

logger = logging.getLogger(__name__)

# 全リソース・全メソッドに適用するメソッド設定のキー
ALL_METHODS = "*/*"
RATE_PATH = f"/{ALL_METHODS}/throttling/rateLimit"
BURST_PATH = f"/{ALL_METHODS}/throttling/burstLimit"

# 閉塞時の値。burst=0 で全リクエストが 429 になる。
BLOCKED_RATE = 0.0
BLOCKED_BURST = 0

HEALTH_TIMEOUT_SEC = 5
HTTP_OK = 200


def _current_throttle(stage: dict) -> tuple[float | None, int | None]:
    """ステージの現在のスロットリング値を返す。設定が無ければ None。"""
    settings = stage.get("methodSettings", {}).get(ALL_METHODS)
    if not settings:
        return None, None
    return (settings.get("throttlingRateLimit"),
            settings.get("throttlingBurstLimit"))


def _set_throttle(cfg: ApiGatewayConfig, *, rate: float, burst: int,
                  dry_run: bool) -> None:
    apigw = client("apigateway", cfg.region)

    # aws apigateway get-stage --rest-api-id <id> --stage-name <stage>
    #   の methodSettings."*/*".throttlingRateLimit / throttlingBurstLimit
    stage = apigw.get_stage(restApiId=cfg.rest_api_id, stageName=cfg.stage)
    current_rate, current_burst = _current_throttle(stage)

    if (current_rate, current_burst) == (rate, burst):
        logger.info("apigateway %s: already rate=%s burst=%s",
                    cfg.region, rate, burst)
        return

    if dry_run:
        logger.info("apigateway %s: would set rate=%s->%s burst=%s->%s",
                    cfg.region, current_rate, rate, current_burst, burst)
        return

    # aws apigateway update-stage --rest-api-id <id> --stage-name <stage>
    #   --patch-operations op=replace,path=/*/*/throttling/rateLimit,value=<v>
    apigw.update_stage(
        restApiId=cfg.rest_api_id,
        stageName=cfg.stage,
        patchOperations=[
            {"op": "replace", "path": RATE_PATH, "value": str(rate)},
            {"op": "replace", "path": BURST_PATH, "value": str(burst)},
        ],
    )
    logger.info("apigateway %s: rate=%s->%s burst=%s->%s",
                cfg.region, current_rate, rate, current_burst, burst)


@lambda_handler("apigateway-block", ApiGatewayConfig, best_effort=True)
def block(cfg: ApiGatewayConfig, event: dict, *, dry_run: bool, context) -> dict:
    """スロットリングを 0 にして閉塞する。"""
    _set_throttle(cfg, rate=BLOCKED_RATE, burst=BLOCKED_BURST, dry_run=dry_run)
    return {}


@lambda_handler("apigateway-enable", ApiGatewayConfig)
def enable(cfg: ApiGatewayConfig, event: dict, *, dry_run: bool, context) -> dict:
    """スロットリングを通常値へ戻して開放する。"""
    override = event.get("throttle") or {}
    _set_throttle(
        cfg,
        rate=float(override.get("rate", cfg.throttle_rate)),
        burst=int(override.get("burst", cfg.throttle_burst)),
        dry_run=dry_run,
    )
    return {}


@lambda_handler("apigateway-check", ApiGatewayConfig)
def check(cfg: ApiGatewayConfig, event: dict, *, dry_run: bool, context) -> dict:
    """開放が効いているか確認する.

    設定確認だけでは「設定は正しいが通らない」を検出できないため、
    ヘルスチェック URL へ実リクエストを 1 回投げる。閉塞が解除されて
    いなければ 429 が返る。
    """
    apigw = client("apigateway", cfg.region)
    stage = apigw.get_stage(restApiId=cfg.rest_api_id, stageName=cfg.stage)
    rate, burst = _current_throttle(stage)

    if not cfg.health_url:
        return {}

    # スキームを検証してから開く。設定ミスで file: 等が渡ることを防ぐ。
    if not cfg.health_url.startswith("https://"):
        raise ValueError(f"HEALTH_URL must be https: {cfg.health_url}")

    try:
        with urllib.request.urlopen(  # noqa: S310 - スキームは上で検証済み
                cfg.health_url, timeout=HEALTH_TIMEOUT_SEC) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code

    if status != HTTP_OK:
        return {"http_status": status, "rate": rate, "burst": burst}
    return {}
