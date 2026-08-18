"""API Gateway の閉塞 / 開放 / 確認.

ステージのスロットリングを 0 にして閉塞し、通常値に戻して開放する。
スロットリングはステージ設定なので再デプロイは不要。

必要な IAM（自関数が対象とするリージョンの ARN のみ）:
    block / enable  apigateway:GET / apigateway:PATCH
                    .../restapis/<id>/stages/<stage>
    check           apigateway:GET
                    .../restapis/<id>  と  .../restapis/<id>/stages/<stage>

ハンドラ（成功時は何も返さない。失敗・未収束は例外で表現する）:
    block   閉塞。入力 {"dry_run": bool}
    enable  開放。入力 {"dry_run": bool,
            "throttle": {"rate": float, "burst": int}}  # throttle は任意
    check   API の状態とスロットリング値を確認。入力 {"dry_run": bool}

check が HTTP リクエストを投げない理由:
    切替で変更するのはステージのスロットリングだけで、これはステージ設定
    のため再デプロイを伴わない。設定が反映されたことは get_stage で確認
    できる。統合先まで含めた到達性の確認には副作用の無いエンドポイントが
    必要になるが、それは用意していない。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from dr_switch.apigateway.config import ApiGatewayConfig
from dr_switch.core import NotRecoverableError, client, lambda_handler

if TYPE_CHECKING:
    from mypy_boto3_apigateway.literals import ApiStatusType

logger = logging.getLogger(__name__)

# 全リソース・全メソッドに適用するメソッド設定のキー
ALL_METHODS = "*/*"
RATE_PATH = f"/{ALL_METHODS}/throttling/rateLimit"
BURST_PATH = f"/{ALL_METHODS}/throttling/burstLimit"

# 閉塞時の値。burst=0 で全リクエストが 429 になる。
BLOCKED_RATE = 0.0
BLOCKED_BURST = 0

# apiStatus の分類。正常でも遷移中でもない値は、待っても解消しないものとして扱う。
#
# UPDATING を正常扱いにするのは、公式に「ステータスメッセージが UPDATING の
# ときも呼び出しは可能」と明記があるため。PENDING / FAILED の意味は公式に
# 記載が無く、名称からの判断。
#
# このフィールドは botocore 1.41.0 でモデルに追加された。それ未満では
# サービスが返していてもパース時に落とされるため、requirements.txt で
# boto3 を 1.41.0 以上に固定している。取得できない場合は確認をスキップする。
HEALTHY_API_STATUSES: frozenset[ApiStatusType] = frozenset({"AVAILABLE", "UPDATING"})
TRANSIENT_API_STATUSES: frozenset[ApiStatusType] = frozenset({"PENDING"})


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
    """API の状態と、スロットリングが開放後の値に戻っているかを確認する。"""
    apigw = client("apigateway", cfg.region)
    problems: dict[str, object] = {}
    fatal: dict[str, object] = {}

    # aws apigateway get-rest-api --rest-api-id <id> の apiStatus
    api = apigw.get_rest_api(restApiId=cfg.rest_api_id)
    status = api.get("apiStatus")
    if status is not None and status not in HEALTHY_API_STATUSES:
        detail = {"api_status": status,
                  "api_status_message": api.get("apiStatusMessage")}
        target = problems if status in TRANSIENT_API_STATUSES else fatal
        target["api"] = detail

    # aws apigateway get-stage --rest-api-id <id> --stage-name <stage>
    #   の methodSettings."*/*".throttlingRateLimit / throttlingBurstLimit
    stage = apigw.get_stage(restApiId=cfg.rest_api_id, stageName=cfg.stage)
    rate, burst = _current_throttle(stage)
    if (rate, burst) != (cfg.throttle_rate, cfg.throttle_burst):
        problems["throttle"] = {
            "rate": rate, "burst": burst,
            "expected_rate": cfg.throttle_rate,
            "expected_burst": cfg.throttle_burst,
        }

    if fatal:
        raise NotRecoverableError(
            json.dumps({"apigateway": fatal}, ensure_ascii=False, default=str))
    return problems
