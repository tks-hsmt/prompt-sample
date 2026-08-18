"""EKS 用の設定."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self

from dr_switch.core import BaseConfig, optional, optional_json, required


@dataclass(frozen=True)
class ClusterConfig:
    """確認対象のクラスタ 1 つ分。"""

    name: str
    namespaces: list[str]


@dataclass(frozen=True)
class EksConfig(BaseConfig):
    clusters: list[ClusterConfig] = field(default_factory=list)
    #: Pod を再起動する既存 Lambda の名前または ARN。
    #: 対象クラスタ・namespace・Pod は呼ばれる側が保持している。
    #: 順序依存が無いため並列に呼び出す。
    pod_restart_functions: list[str] = field(default_factory=list)
    #: 呼ばれる側は Pod の起動完了を待つため、既定より長い読み取り
    #: タイムアウトが要る。呼ばれる側の Timeout に合わせて設定する。
    pod_restart_timeout: int = 300

    @classmethod
    def from_env(cls) -> Self:
        raw = optional_json("EKS_CLUSTERS", [])
        return cls(
            region=required("REGION"),
            clusters=[ClusterConfig(**c) for c in raw],
            pod_restart_functions=optional_json("POD_RESTART_FUNCTIONS", []),
            pod_restart_timeout=int(optional("POD_RESTART_TIMEOUT", "300")),
        )
