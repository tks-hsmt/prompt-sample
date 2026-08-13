"""DR 切替 Lambda 共通モジュール.

配置方針:
    東京・大阪の両リージョンに同一構成をデプロイする。
    実行するのは常に「これから ACTIVE になる側」のリージョン。
        東京 -> 大阪の切替  : 大阪の Step Functions / Lambda が動く
        大阪 -> 東京の切戻し: 東京の Step Functions / Lambda が動く

    したがって各 Lambda から見て
        SELF = 自リージョン = これから ACTIVE になる側 = 開放する対象
        PEER = 相手リージョン = これまで ACTIVE だった側 = 閉塞する対象
    となり、切替方向は「どのリージョンの Step Functions を叩いたか」で
    一意に決まる。入力に direction を持たせない（取り違え事故が起きない）。
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from typing import Any, Literal, NoReturn

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

Role = Literal["self", "peer"]

# boto3 が送出しうる例外の総称。これ以外（KeyError 等）は自分のコードの
# バグなので握りつぶさず、そのまま送出させる。
AWS_ERRORS = (ClientError, BotoCoreError)


# ---------------------------------------------------------------------------
# 例外設計
#
#   ConfigError      : 環境変数の不備。デプロイ時の設定ミス。
#   RetryableError   : 一時的な失敗。Step Functions の Retry で再試行させる。
#   BestEffortFailed : 旧 ACTIVE 側（PEER）の操作失敗。Catch で記録して続行。
#                      リージョン障害中は PEER のコントロールプレーンが
#                      応答しないため、閉塞失敗はワークフローを止めない。
#   FatalError       : 新 ACTIVE 側（SELF）の操作失敗。切替そのものが
#                      成立しないので、ワークフローを止める。
#
# 観測系 Lambda（check_*）はこれらを投げず、結果を dict で返す。
# 「制御フローの分岐材料は戻り値、失敗は例外」の切り分け。
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    """環境変数の不足・不正。"""


class RetryableError(Exception):
    """スロットリング等の一時エラー。SFN の Retry 対象。"""


class BestEffortFailed(Exception):
    """PEER 側操作の恒久的失敗。SFN の Catch で記録して続行。"""


class FatalError(Exception):
    """SELF 側操作の失敗。ワークフローを停止させる。"""


RETRYABLE_CODES = frozenset({
    "ThrottlingException",
    "Throttling",
    "TooManyRequestsException",
    "RequestLimitExceeded",
    "ServiceUnavailable",
    "InternalFailure",
    "InternalServerError",
    "InternalServerErrorException",
    "LimitExceededException",
    "ConflictException",
})


def raise_classified(exc: Exception, *, role: Role, what: str) -> NoReturn:
    """AWS 例外を Retryable / BestEffortFailed / FatalError に振り分けて送出する.

    role が "peer"（閉塞対象）なら失敗許容、"self"（開放対象）なら致命的。
    必ず送出するため戻り値型は NoReturn。
    """
    code = ""
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")

    if code in RETRYABLE_CODES and code:
        logger.warning("retryable error: %s: %s", what, exc)
        raise RetryableError(f"{what}: {code}: {exc}") from exc

    if role == "peer":
        # 旧 ACTIVE 側は障害中で到達不能な可能性がある。想定内。
        logger.warning("best-effort operation failed: %s: %s", what, exc)
        raise BestEffortFailed(f"{what}: {code or type(exc).__name__}: {exc}") from exc

    logger.error("fatal error on new active region: %s: %s", what, exc)
    raise FatalError(f"{what}: {code or type(exc).__name__}: {exc}") from exc


# ---------------------------------------------------------------------------
# 設定（環境変数）
#
# Terraform から SELF_* / PEER_* を注入する。東京デプロイと大阪デプロイで
# self / peer を入れ替えて同じモジュールを呼ぶだけでよい。
# リスト・マップは JSON 文字列で渡す。
# ---------------------------------------------------------------------------


def _env(role: Role, key: str, default: str | None = None) -> str:
    name = f"{role.upper()}_{key}"
    value = os.environ.get(name, default)
    if value is None:
        raise ConfigError(f"environment variable not set: {name}")
    return value


def _env_json(role: Role, key: str, default: Any) -> Any:
    raw = os.environ.get(f"{role.upper()}_{key}")
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {role.upper()}_{key}: {exc}") from exc


@dataclass(frozen=True)
class RegionConfig:
    """片側リージョンの設定。属性アクセスなのでタイポが早期に露見する。"""

    role: Role
    region: str
    rest_api_id: str
    stage: str
    # EventBridge Scheduler のスケジュールグループ（自チーム専用グループ）
    schedule_group: str = "default"
    # 切替対象スケジュールの接頭辞。未設定ならグループ内の全件が対象になる。
    schedule_name_prefix: str = ""
    health_url: str | None = None
    function_names: list[str] = field(default_factory=list)
    table_names: list[str] = field(default_factory=list)
    target_group_arns: list[str] = field(default_factory=list)
    alarm_prefix: str = ""
    eks_cluster_name: str | None = None
    # 確認対象の namespace。Deployment 名と必要数はクラスタから読むため不要。
    eks_namespaces: list[str] = field(default_factory=list)
    hybrid_node_selector: str = "eks.amazonaws.com/compute-type=hybrid"
    # 案 A（切替時に Status をトグル）でのみ使う。案 B では空でよい。
    replication_buckets: list[str] = field(default_factory=list)


def config(role: Role) -> RegionConfig:
    if role not in ("self", "peer"):
        raise ConfigError(f"invalid role: {role}")
    return RegionConfig(
        role=role,
        region=_env(role, "REGION"),
        rest_api_id=_env(role, "REST_API_ID"),
        stage=_env(role, "STAGE"),
        schedule_group=_env(role, "SCHEDULE_GROUP", "default"),
        schedule_name_prefix=_env(role, "SCHEDULE_NAME_PREFIX", ""),
        health_url=os.environ.get(f"{role.upper()}_HEALTH_URL"),
        function_names=_env_json(role, "FUNCTION_NAMES", []),
        table_names=_env_json(role, "TABLE_NAMES", []),
        target_group_arns=_env_json(role, "TARGET_GROUP_ARNS", []),
        alarm_prefix=_env(role, "ALARM_PREFIX", ""),
        eks_cluster_name=os.environ.get(f"{role.upper()}_EKS_CLUSTER_NAME"),
        eks_namespaces=_env_json(role, "EKS_NAMESPACES", []),
        hybrid_node_selector=_env(
            role, "HYBRID_NODE_SELECTOR", "eks.amazonaws.com/compute-type=hybrid"),
        replication_buckets=_env_json(role, "REPLICATION_BUCKETS", []),
    )


@cache
def client(service: str, region: str):
    """リージョンを必ず明示する。デフォルトリージョン依存は事故の元。

    ウォームスタート時にクライアントを再利用するためキャッシュする。
    """
    return boto3.client(service, region_name=region)


def account_id(context) -> str:
    """STS を呼ばずに Lambda の ARN からアカウント ID を取り出す。"""
    # arn:aws:lambda:<region>:<account-id>:function:<name>
    return context.invoked_function_arn.split(":")[4]


# ---------------------------------------------------------------------------
# 観測系 Lambda の共通処理
# ---------------------------------------------------------------------------


def guard(name: str, fn: Callable[..., dict], *args, **kwargs) -> dict:
    """個別チェックを隔離する。失敗は結果に含めるだけで送出しない.

    1 つの API エラーで全項目が見えなくなると、保守者が原因を切り分け
    られないため。握りつぶす代わりに必ずログへ残す。
    """
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - 観測系は何があっても結果を返す
        logger.exception("check failed: %s", name)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def check_result(check: str, region: str, detail: dict[str, dict]) -> dict:
    """観測系 Lambda の戻り値エンベロープを一元化する.

    合否は返すが例外は投げない。判定と分岐は Step Functions の Choice に任せる。
    """
    ready = all(item.get("ok") for item in detail.values())
    result = {"check": check, "region": region, "ready": ready, "detail": detail}
    logger.info("check=%s region=%s ready=%s ng=%s", check, region, ready,
                [k for k, v in detail.items() if not v.get("ok")])
    return result
