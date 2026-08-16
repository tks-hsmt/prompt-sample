"""EKS 用の設定."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self

from dr_switch.core import BaseConfig, optional_json, required


@dataclass(frozen=True)
class ClusterConfig:
    """確認対象のクラスタ 1 つ分。"""

    name: str
    namespaces: list[str]


@dataclass(frozen=True)
class EksConfig(BaseConfig):
    clusters: list[ClusterConfig] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> Self:
        raw = optional_json("EKS_CLUSTERS", [])
        return cls(
            region=required("REGION"),
            clusters=[ClusterConfig(**c) for c in raw],
        )
