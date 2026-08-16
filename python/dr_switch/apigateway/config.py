"""API Gateway 用の設定."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from dr_switch.core import BaseConfig, optional, required

DEFAULT_THROTTLE_RATE = "10000"
DEFAULT_THROTTLE_BURST = "5000"


@dataclass(frozen=True)
class ApiGatewayConfig(BaseConfig):
    rest_api_id: str
    stage: str
    throttle_rate: float = float(DEFAULT_THROTTLE_RATE)
    throttle_burst: int = int(DEFAULT_THROTTLE_BURST)
    health_url: str | None = None

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            region=required("REGION"),
            rest_api_id=required("REST_API_ID"),
            stage=required("STAGE"),
            throttle_rate=float(optional("THROTTLE_RATE", DEFAULT_THROTTLE_RATE)),
            throttle_burst=int(optional("THROTTLE_BURST", DEFAULT_THROTTLE_BURST)),
            health_url=optional("HEALTH_URL"),
        )
