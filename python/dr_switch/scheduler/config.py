"""EventBridge Scheduler 用の設定."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from dr_switch.core import BaseConfig, required


@dataclass(frozen=True)
class SchedulerBaseConfig(BaseConfig):
    """全ハンドラ共通。操作対象のスケジュールグループ。"""

    schedule_group: str

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            region=required("REGION"),
            schedule_group=required("SCHEDULE_GROUP"),
        )


@dataclass(frozen=True)
class SchedulerBlockConfig(SchedulerBaseConfig):
    """block 用。停止は State を定数で指定するので追加の項目は無い。"""


@dataclass(frozen=True)
class SchedulerEnableConfig(SchedulerBaseConfig):
    """enable 用。開始も State を定数で指定するので追加の項目は無い。"""


@dataclass(frozen=True)
class SchedulerCheckConfig(SchedulerBaseConfig):
    """check 用。追加の項目は無い。"""
