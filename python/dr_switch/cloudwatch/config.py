"""CloudWatch 用の設定."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from dr_switch.core import BaseConfig, optional, required


@dataclass(frozen=True)
class AlarmConfig(BaseConfig):
    alarm_prefix: str = ""

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            region=required("REGION"),
            alarm_prefix=optional("ALARM_PREFIX", ""),
        )
