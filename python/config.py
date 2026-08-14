"""環境変数からの設定読み込み.

SELF_* / PEER_* を Terraform から注入する。Lambda ごとに必要な項目が
違うため、設定クラスもリソース単位に分ける。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Literal, Self

Role = Literal["self", "peer"]

DEFAULT_THROTTLE_RATE = "10000"
DEFAULT_THROTTLE_BURST = "5000"


def _required(role: Role, key: str) -> str:
    """未設定なら KeyError。必須項目に使う。"""
    name = f"{role.upper()}_{key}"
    value = os.environ.get(name)
    if value is None:
        raise KeyError(f"environment variable not set: {name}")
    return value


def _optional(role: Role, key: str, default: str | None = None) -> str | None:
    """省略可能な環境変数。"""
    return os.environ.get(f"{role.upper()}_{key}", default)


def _optional_json(role: Role, key: str, default: Any) -> Any:
    raw = os.environ.get(f"{role.upper()}_{key}")
    return json.loads(raw) if raw else default


@dataclass(frozen=True)
class BaseConfig:
    """全 Lambda が使う最小限。"""

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
            throttle_rate=float(_optional(role, "THROTTLE_RATE",
                                          DEFAULT_THROTTLE_RATE)),
            throttle_burst=int(_optional(role, "THROTTLE_BURST",
                                         DEFAULT_THROTTLE_BURST)),
            health_url=_optional(role, "HEALTH_URL"),
        )


@dataclass(frozen=True)
class SchedulerConfig(BaseConfig):
    """dr-scheduler."""

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
    """dr-check-alarms."""

    alarm_prefix: str = ""

    @classmethod
    def from_env(cls, role: Role) -> Self:
        return cls(
            role=role,
            region=_required(role, "REGION"),
            alarm_prefix=_optional(role, "ALARM_PREFIX", ""),
        )


@dataclass(frozen=True)
class ClusterConfig:
    """確認対象のクラスタ 1 つ分。"""

    name: str
    namespaces: list[str]


@dataclass(frozen=True)
class EksConfig(BaseConfig):
    """dr-check-workload."""

    clusters: list[ClusterConfig] = field(default_factory=list)

    @classmethod
    def from_env(cls, role: Role) -> Self:
        raw = _optional_json(role, "EKS_CLUSTERS", [])
        return cls(
            role=role,
            region=_required(role, "REGION"),
            clusters=[ClusterConfig(**c) for c in raw],
        )
