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

import json
import os

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError

# ---------------------------------------------------------------------------
# 例外設計
#
#   RetryableError   : 一時的な失敗。Step Functions の Retry で再試行させる。
#   BestEffortFailed : 旧 ACTIVE 側（PEER）の操作失敗。Catch で記録して続行する。
#                      リージョン障害中は PEER のコントロールプレーンが
#                      応答しないため、閉塞失敗はワークフローを止めない。
#   FatalError       : 新 ACTIVE 側（SELF）の操作失敗。切替そのものが
#                      成立しないので、ワークフローを止める。
#
# 観測系 Lambda（check_*）はこれらを投げず、結果を dict で返す。
# 「制御フローの分岐材料は戻り値、失敗は例外」の切り分け。
# ---------------------------------------------------------------------------


class RetryableError(Exception):
    """スロットリング等の一時エラー。SFN の Retry 対象。"""


class BestEffortFailed(Exception):
    """PEER 側操作の恒久的失敗。SFN の Catch で記録して続行。"""


class FatalError(Exception):
    """SELF 側操作の失敗。ワークフローを停止させる。"""


RETRYABLE_CODES = {
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
}


def raise_classified(exc: Exception, *, role: str, what: str) -> None:
    """boto3 の例外を RetryableError / BestEffortFailed / FatalError に振り分ける.

    role: "peer"（閉塞対象）なら失敗許容、"self"（開放対象）なら致命的。
    """
    if isinstance(exc, EndpointConnectionError):
        # リージョンごと到達不能。PEER なら想定内。
        if role == "peer":
            raise BestEffortFailed(f"{what}: endpoint unreachable: {exc}") from exc
        raise FatalError(f"{what}: endpoint unreachable: {exc}") from exc

    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        if code in RETRYABLE_CODES:
            raise RetryableError(f"{what}: {code}: {exc}") from exc
        if role == "peer":
            raise BestEffortFailed(f"{what}: {code}: {exc}") from exc
        raise FatalError(f"{what}: {code}: {exc}") from exc

    if role == "peer":
        raise BestEffortFailed(f"{what}: {exc}") from exc
    raise FatalError(f"{what}: {exc}") from exc


# ---------------------------------------------------------------------------
# 設定（環境変数）
#
# Terraform から SELF_* / PEER_* を注入する。東京デプロイと大阪デプロイで
# self / peer を入れ替えて同じモジュールを呼ぶだけでよい。
# リスト系は JSON 文字列で渡す。
# ---------------------------------------------------------------------------


def _env(role: str, key: str, default=None):
    name = f"{role.upper()}_{key}"
    value = os.environ.get(name, default)
    if value is None:
        raise FatalError(f"environment variable not set: {name}")
    return value


def _env_json(role: str, key: str, default):
    raw = os.environ.get(f"{role.upper()}_{key}")
    if raw in (None, ""):
        return default
    return json.loads(raw)


def config(role: str) -> dict:
    """role は "self" か "peer"."""
    if role not in ("self", "peer"):
        raise FatalError(f"invalid role: {role}")
    return {
        "role": role,
        "region": _env(role, "REGION"),
        "rest_api_id": _env(role, "REST_API_ID"),
        "stage": _env(role, "STAGE"),
        "event_bus": _env(role, "EVENT_BUS", "default"),
        "health_url": os.environ.get(f"{role.upper()}_HEALTH_URL"),
        "function_names": _env_json(role, "FUNCTION_NAMES", []),
        "table_names": _env_json(role, "TABLE_NAMES", []),
        "target_group_arns": _env_json(role, "TARGET_GROUP_ARNS", []),
        "min_healthy_targets": int(os.environ.get(
            f"{role.upper()}_MIN_HEALTHY_TARGETS", "1")),
        "alarm_prefix": os.environ.get(f"{role.upper()}_ALARM_PREFIX", ""),
        "eks_cluster_name": os.environ.get(f"{role.upper()}_EKS_CLUSTER_NAME"),
        "eks_namespaces": _env_json(role, "EKS_NAMESPACES", []),
        # {"namespace/deployment": 期待レプリカ数}
        "eks_deployments": _env_json(role, "EKS_DEPLOYMENTS", {}),
        "hybrid_node_selector": os.environ.get(
            f"{role.upper()}_HYBRID_NODE_SELECTOR",
            "eks.amazonaws.com/compute-type=hybrid"),
    }


def client(service: str, region: str):
    """リージョンを必ず明示する。デフォルトリージョン依存は事故の元。"""
    return boto3.client(service, region_name=region)


def account_id(context) -> str:
    """STS を呼ばずに Lambda の ARN からアカウント ID を取り出す。"""
    # arn:aws:lambda:<region>:<account-id>:function:<name>
    return context.invoked_function_arn.split(":")[4]
