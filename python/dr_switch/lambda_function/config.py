"""Lambda 用の設定."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self

from dr_switch.core import BaseConfig, optional_json, required


@dataclass(frozen=True)
class LambdaBaseConfig(BaseConfig):
    """全ハンドラ共通。確認対象のリソース。"""

    function_names: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            region=required("REGION"),
            function_names=optional_json("FUNCTION_NAMES", []),
        )


@dataclass(frozen=True)
class LambdaCheckConfig(LambdaBaseConfig):
    """check 用。追加の項目は無い。"""
