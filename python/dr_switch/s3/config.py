"""S3 用の設定."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self

from dr_switch.core import BaseConfig, optional, optional_json, required


@dataclass(frozen=True)
class S3BaseConfig(BaseConfig):
    """全ハンドラ共通。操作対象のバケット。"""

    replication_buckets: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            region=required("REGION"),
            replication_buckets=optional_json("REPLICATION_BUCKETS", []),
        )


@dataclass(frozen=True)
class S3BlockConfig(S3BaseConfig):
    """block 用。Status を定数で指定するので追加の項目は無い。"""


@dataclass(frozen=True)
class S3EnableConfig(S3BaseConfig):
    """enable 用。追加の項目は無い。"""


@dataclass(frozen=True)
class S3CheckConfig(S3BaseConfig):
    """check 用。レプリケーションの滞留を見る期間を持つ。"""

    #: OperationsPendingReplication を遡って見る秒数。
    #: メトリクスは分単位で発行されるため、最低でも数分は必要。
    replication_lookback: int = 300

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            region=required("REGION"),
            replication_buckets=optional_json("REPLICATION_BUCKETS", []),
            replication_lookback=int(optional("REPLICATION_LOOKBACK", "300")),
        )
