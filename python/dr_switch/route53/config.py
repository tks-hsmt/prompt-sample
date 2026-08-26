"""Route 53 用の設定."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from dr_switch.core import BaseConfig, required


@dataclass(frozen=True)
class Route53BaseConfig(BaseConfig):
    """全ハンドラ共通。切替対象のレコードと向き先。

    向き先（alias_dns_name / alias_hosted_zone_id）は切替先リージョンの
    VPC エンドポイントを指す。ホストゾーン ID はリージョン固有の固定値で、
    VPC エンドポイントごとに変わるものではない。
    """

    #: プライベートホストゾーンの ID
    hosted_zone_id: str
    #: 切替対象のレコード名（末尾のドット有無は問わない）
    record_name: str
    #: 切替先 VPC エンドポイントの DNS 名
    alias_dns_name: str
    #: 切替先 VPC エンドポイントのホストゾーン ID
    alias_hosted_zone_id: str

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            region=required("REGION"),
            hosted_zone_id=required("HOSTED_ZONE_ID"),
            record_name=required("RECORD_NAME"),
            alias_dns_name=required("ALIAS_DNS_NAME"),
            alias_hosted_zone_id=required("ALIAS_HOSTED_ZONE_ID"),
        )


@dataclass(frozen=True)
class Route53SwitchConfig(Route53BaseConfig):
    """switch 用。追加の項目は無い。"""


@dataclass(frozen=True)
class Route53CheckConfig(Route53BaseConfig):
    """check 用。追加の項目は無い。"""
