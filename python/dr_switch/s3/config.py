"""S3 用の設定."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self

from dr_switch.core import BaseConfig, optional_json, required


@dataclass(frozen=True)
class S3Config(BaseConfig):
    replication_buckets: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            region=required("REGION"),
            replication_buckets=optional_json("REPLICATION_BUCKETS", []),
        )
