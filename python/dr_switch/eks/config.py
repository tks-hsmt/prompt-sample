"""EKS 用の設定."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Self

from dr_switch.core import BaseConfig, optional, optional_json, required


@dataclass(frozen=True)
class RestartTarget:
    """rollout restart の対象ワークロード。"""

    kind: str  # "Deployment" | "DaemonSet"
    name: str


@dataclass(frozen=True)
class NamespaceConfig:
    """確認対象の namespace 1 つ分。"""

    name: str
    #: rollout restart の対象。空なら再起動しない（check の対象にはなる）
    restart_targets: list[RestartTarget] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Self:
        return cls(
            name=raw["name"],
            restart_targets=[RestartTarget(**t)
                             for t in raw.get("restart_targets", [])],
        )


@dataclass(frozen=True)
class ClusterConfig:
    """確認対象のクラスタ 1 つ分。"""

    name: str
    namespaces: list[NamespaceConfig]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Self:
        return cls(
            name=raw["name"],
            namespaces=[NamespaceConfig.from_dict(n) for n in raw["namespaces"]],
        )


@dataclass(frozen=True)
class EksBaseConfig(BaseConfig):
    """Kubernetes API を叩くハンドラ共通。"""

    clusters: list[ClusterConfig] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> Self:
        raw = optional_json("EKS_CLUSTERS", [])
        return cls(
            region=required("REGION"),
            clusters=[ClusterConfig.from_dict(c) for c in raw],
        )


@dataclass(frozen=True)
class EksRolloutRestartConfig(EksBaseConfig):
    """rollout_restart 用。対象は clusters の restart_targets で指定する。"""


@dataclass(frozen=True)
class EksCheckConfig(EksBaseConfig):
    """check 用。追加の項目は無い。"""


@dataclass(frozen=True)
class PodRestartBaseConfig(BaseConfig):
    """既存の Pod 再起動 Lambda を呼び出すハンドラ共通.

    EKS のリソースではなく呼び出す関数を指すので、EksBaseConfig とは別の概念。
    対象クラスタ・namespace・Pod は呼ばれる側が保持している。
    """

    #: 呼び出す関数の名前または ARN。順序依存が無いため並列に呼ぶ。
    functions: list[str] = field(default_factory=list)
    #: 呼ばれる側は Pod の起動完了を待つため、既定より長い読み取り
    #: タイムアウトが要る。呼ばれる側の Timeout に合わせて設定する。
    timeout: int = 300

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            region=required("REGION"),
            functions=optional_json("POD_RESTART_FUNCTIONS", []),
            timeout=int(optional("POD_RESTART_TIMEOUT", "300")),
        )


@dataclass(frozen=True)
class PodRestartConfig(PodRestartBaseConfig):
    """restart_pods 用。追加の項目は無い。"""
