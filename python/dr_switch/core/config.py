"""環境変数の読み込みヘルパと、全リソース共通の設定基底.

各 Lambda は、環境変数で指定された 1 つのリージョンだけを対象にする。
リソース固有の設定クラスは各リソースパッケージの config.py に置く。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Self


def required(key: str) -> str:
    """未設定なら KeyError。必須項目に使う。"""
    value = os.environ.get(key)
    if value is None:
        raise KeyError(f"environment variable not set: {key}")
    return value


def optional(key: str, default: str | None = None) -> str | None:
    """省略可能な環境変数。"""
    return os.environ.get(key, default)


def optional_json(key: str, default: Any) -> Any:
    raw = os.environ.get(key)
    return json.loads(raw) if raw else default


@dataclass(frozen=True)
class BaseConfig:
    """全 Lambda が使う最小限。"""

    region: str

    @classmethod
    def from_env(cls) -> Self:
        return cls(region=required("REGION"))
