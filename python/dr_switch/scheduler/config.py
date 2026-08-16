"""EventBridge Scheduler 用の設定."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from dr_switch.core import BaseConfig, required


@dataclass(frozen=True)
class SchedulerConfig(BaseConfig):
    schedule_group: str

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            region=required("REGION"),
            schedule_group=required("SCHEDULE_GROUP"),
        )
