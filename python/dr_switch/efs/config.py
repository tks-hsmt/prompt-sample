"""EFS 用の設定."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self

from dr_switch.core.config import BaseConfig, optional_json, required


@dataclass(frozen=True)
class EfsConfig(BaseConfig):
    #: ファイルシステム ID。マウントターゲットはここから辿れるので指定不要
    file_system_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            region=required("REGION"),
            file_system_ids=optional_json("FILE_SYSTEM_IDS", []),
        )
