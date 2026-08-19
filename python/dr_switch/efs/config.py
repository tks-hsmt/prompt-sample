"""EFS 用の設定."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self

from dr_switch.core import BaseConfig, optional_json, required


@dataclass(frozen=True)
class EfsBaseConfig(BaseConfig):
    """全ハンドラ共通。確認対象のリソース。"""

    #: ファイルシステム ID。マウントターゲットはここから辿れるので指定不要
    file_system_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            region=required("REGION"),
            file_system_ids=optional_json("FILE_SYSTEM_IDS", []),
        )


@dataclass(frozen=True)
class EfsCheckConfig(EfsBaseConfig):
    """check 用。追加の項目は無い。"""
