"""環境変数からの設定読み込み.

Terraform から SELF_* / PEER_* を注入する。東京デプロイと大阪デプロイで
self / peer を入れ替えて同じモジュールを呼ぶだけでよい。
リスト・マップは JSON 文字列で渡す。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["self", "peer"]


def _env(role: Role, key: str, default: str | None = None) -> str:
    name = f"{role.upper()}_{key}"
    value = os.environ.get(name, default)
    if value is None:
        raise KeyError(f"environment variable not set: {name}")
    return value


def _env_json(role: Role, key: str, default: Any) -> Any:
    raw = os.environ.get(f"{role.upper()}_{key}")
    return json.loads(raw) if raw else default


@dataclass(frozen=True)
class RegionConfig:
    """片側リージョンの設定。属性アクセスなのでタイポが早期に露見する。"""

    role: Role
    region: str
    rest_api_id: str = ""
    stage: str = ""
    # 開放時に戻すスロットリング値。アカウントのデフォルトと同値にしておく。
    throttle_rate: float = 10000.0
    throttle_burst: int = 5000
    health_url: str | None = None
    schedule_group: str = "default"
    function_names: list[str] = field(default_factory=list)
    table_names: list[str] = field(default_factory=list)
    target_group_arns: list[str] = field(default_factory=list)
    alarm_prefix: str = ""
    eks_cluster_name: str = ""
    # 確認対象の namespace。Deployment 名と必要数はクラスタから読むため不要。
    eks_namespaces: list[str] = field(default_factory=list)
    hybrid_node_selector: str = "eks.amazonaws.com/compute-type=hybrid"
    replication_buckets: list[str] = field(default_factory=list)


def config(role: Role) -> RegionConfig:
    return RegionConfig(
        role=role,
        region=_env(role, "REGION"),
        rest_api_id=_env(role, "REST_API_ID", ""),
        stage=_env(role, "STAGE", ""),
        throttle_rate=float(_env(role, "THROTTLE_RATE", "10000")),
        throttle_burst=int(_env(role, "THROTTLE_BURST", "5000")),
        health_url=os.environ.get(f"{role.upper()}_HEALTH_URL"),
        schedule_group=_env(role, "SCHEDULE_GROUP", "default"),
        function_names=_env_json(role, "FUNCTION_NAMES", []),
        table_names=_env_json(role, "TABLE_NAMES", []),
        target_group_arns=_env_json(role, "TARGET_GROUP_ARNS", []),
        alarm_prefix=_env(role, "ALARM_PREFIX", ""),
        eks_cluster_name=_env(role, "EKS_CLUSTER_NAME", ""),
        eks_namespaces=_env_json(role, "EKS_NAMESPACES", []),
        hybrid_node_selector=_env(
            role, "HYBRID_NODE_SELECTOR", "eks.amazonaws.com/compute-type=hybrid"),
        replication_buckets=_env_json(role, "REPLICATION_BUCKETS", []),
    )
