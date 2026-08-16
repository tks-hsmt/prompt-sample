"""NLB 用の設定."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self

from dr_switch.core import BaseConfig, optional_json, required


@dataclass(frozen=True)
class NlbConfig(BaseConfig):
    target_group_arns: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            region=required("REGION"),
            target_group_arns=optional_json("TARGET_GROUP_ARNS", []),
        )
