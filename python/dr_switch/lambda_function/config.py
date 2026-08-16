"""Lambda 用の設定."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self

from dr_switch.core import BaseConfig, optional_json, required


@dataclass(frozen=True)
class LambdaConfig(BaseConfig):
    function_names: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            region=required("REGION"),
            function_names=optional_json("FUNCTION_NAMES", []),
        )
