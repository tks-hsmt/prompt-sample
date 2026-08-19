"""API Gateway 用の設定.

リソースごとに Base を置き、ハンドラごとにサブクラスを作る。追加項目が
無いハンドラでも空のサブクラスを定義し、全リソースで構造を揃える。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from dr_switch.core import BaseConfig, required


@dataclass(frozen=True)
class ApiGatewayBaseConfig(BaseConfig):
    """全ハンドラ共通。操作対象のステージ。"""

    rest_api_id: str
    stage: str

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            region=required("REGION"),
            rest_api_id=required("REST_API_ID"),
            stage=required("STAGE"),
        )


@dataclass(frozen=True)
class ApiGatewayBlockConfig(ApiGatewayBaseConfig):
    """block 用。閉塞は定数 0 を使うので追加の項目は無い。"""


@dataclass(frozen=True)
class ApiGatewayEnableConfig(ApiGatewayBaseConfig):
    """enable 用。開放後のスロットリング値。"""

    throttle_rate: float
    throttle_burst: int

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            region=required("REGION"),
            rest_api_id=required("REST_API_ID"),
            stage=required("STAGE"),
            throttle_rate=float(required("THROTTLE_RATE")),
            throttle_burst=int(required("THROTTLE_BURST")),
        )


@dataclass(frozen=True)
class ApiGatewayCheckConfig(ApiGatewayEnableConfig):
    """check 用。enable が設定した値と一致するかを確認する。"""
