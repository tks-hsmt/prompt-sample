"""環境変数からの設定読み込み.

Terraform から SELF_* / PEER_* を注入する。東京デプロイと大阪デプロイで
self / peer を入れ替えて同じモジュールを呼ぶだけでよい。
リスト・マップは JSON 文字列で渡す。

Lambda はリソース単位に分割しているため、設定クラスもリソース単位に分ける。
1 つの巨大な設定クラスを全 Lambda で共有すると

    - どの Lambda がどの環境変数を必要とするのかコードから読めない
    - ある Lambda にとって必須の項目でも、他の Lambda には不要なので
      すべて省略可能にせざるを得ず、設定漏れを検出できない
    - 無関係なフィールドが補完に出て、取り違えても静的に気づけない

という問題が出る。リソース単位に分けることで、必須項目を _required で
宣言でき、設定漏れが from_env の時点で止まる。

必須と省略可能を関数で分けている（_required / _optional）。
「default が None かどうか」で必須性を表す方式にすると、
「省略可能で既定値が None」の項目（HEALTH_URL）を表現できず、
そこだけ os.environ を直接呼ぶことになるため。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Literal, Self

Role = Literal["self", "peer"]

DEFAULT_THROTTLE_RATE = "10000"
DEFAULT_THROTTLE_BURST = "5000"
DEFAULT_HYBRID_NODE_SELECTOR = "eks.amazonaws.com/compute-type=hybrid"


def _required(role: Role, key: str) -> str:
    """未設定なら停止する環境変数。デプロイ時の設定漏れを即座に露見させる。"""
    name = f"{role.upper()}_{key}"
    value = os.environ.get(name)
    if value is None:
        raise KeyError(f"environment variable not set: {name}")
    return value


def _optional(role: Role, key: str, default: str | None = None) -> str | None:
    """省略可能な環境変数。既定値が None のものもここで扱える。"""
    return os.environ.get(f"{role.upper()}_{key}", default)


def _optional_json(role: Role, key: str, default: Any) -> Any:
    raw = os.environ.get(f"{role.upper()}_{key}")
    return json.loads(raw) if raw else default


@dataclass(frozen=True)
class BaseConfig:
    """全 Lambda が使う最小限。client() と例外分類にリージョンと role が要る。"""

    role: Role
    region: str

    @classmethod
    def from_env(cls, role: Role) -> Self:
        return cls(role=role, region=_required(role, "REGION"))


@dataclass(frozen=True)
class ApiGatewayConfig(BaseConfig):
    """dr-apigw / dr-check-apigw."""

    rest_api_id: str
    stage: str
    throttle_rate: float = float(DEFAULT_THROTTLE_RATE)
    throttle_burst: int = int(DEFAULT_THROTTLE_BURST)
    health_url: str | None = None

    @classmethod
    def from_env(cls, role: Role) -> Self:
        return cls(
            role=role,
            region=_required(role, "REGION"),
            rest_api_id=_required(role, "REST_API_ID"),
            stage=_required(role, "STAGE"),
            # 開放時に戻す値。アカウントのデフォルトと同値にしておく。
            throttle_rate=float(_optional(role, "THROTTLE_RATE",
                                          DEFAULT_THROTTLE_RATE)),
            throttle_burst=int(_optional(role, "THROTTLE_BURST",
                                         DEFAULT_THROTTLE_BURST)),
            # ヘルスチェック経路が無い環境もあるため省略可能
            health_url=_optional(role, "HEALTH_URL"),
        )


@dataclass(frozen=True)
class SchedulerConfig(BaseConfig):
    """dr-scheduler. 自チーム専用のスケジュールグループを指定する。"""

    schedule_group: str

    @classmethod
    def from_env(cls, role: Role) -> Self:
        return cls(
            role=role,
            region=_required(role, "REGION"),
            schedule_group=_required(role, "SCHEDULE_GROUP"),
        )


@dataclass(frozen=True)
class S3Config(BaseConfig):
    """dr-s3-replication / dr-check-s3."""

    replication_buckets: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls, role: Role) -> Self:
        return cls(
            role=role,
            region=_required(role, "REGION"),
            replication_buckets=_optional_json(role, "REPLICATION_BUCKETS", []),
        )


@dataclass(frozen=True)
class LambdaConfig(BaseConfig):
    """dr-check-lambda."""

    function_names: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls, role: Role) -> Self:
        return cls(
            role=role,
            region=_required(role, "REGION"),
            function_names=_optional_json(role, "FUNCTION_NAMES", []),
        )


@dataclass(frozen=True)
class DynamoDbConfig(BaseConfig):
    """dr-check-dynamodb."""

    table_names: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls, role: Role) -> Self:
        return cls(
            role=role,
            region=_required(role, "REGION"),
            table_names=_optional_json(role, "TABLE_NAMES", []),
        )


@dataclass(frozen=True)
class NlbConfig(BaseConfig):
    """dr-check-nlb."""

    target_group_arns: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls, role: Role) -> Self:
        return cls(
            role=role,
            region=_required(role, "REGION"),
            target_group_arns=_optional_json(role, "TARGET_GROUP_ARNS", []),
        )


@dataclass(frozen=True)
class AlarmConfig(BaseConfig):
    """dr-check-alarms. 接頭辞を空にすると全アラームが対象になる。"""

    alarm_prefix: str = ""

    @classmethod
    def from_env(cls, role: Role) -> Self:
        return cls(
            role=role,
            region=_required(role, "REGION"),
            alarm_prefix=_optional(role, "ALARM_PREFIX", ""),
        )


@dataclass(frozen=True)
class EksConfig(BaseConfig):
    """dr-check-workload."""

    cluster_name: str
    namespaces: list[str] = field(default_factory=list)
    hybrid_node_selector: str = DEFAULT_HYBRID_NODE_SELECTOR

    @classmethod
    def from_env(cls, role: Role) -> Self:
        return cls(
            role=role,
            region=_required(role, "REGION"),
            cluster_name=_required(role, "EKS_CLUSTER_NAME"),
            namespaces=_optional_json(role, "EKS_NAMESPACES", []),
            hybrid_node_selector=_optional(role, "HYBRID_NODE_SELECTOR",
                                           DEFAULT_HYBRID_NODE_SELECTOR),
        )
