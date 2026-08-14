"""boto3 クライアントの生成."""

from __future__ import annotations

from functools import cache

import boto3
from botocore.config import Config

# 既定は connect / read とも 60 秒で長すぎるため明示する。
# max_attempts は「リトライ回数」であって総試行回数ではない（1 なら合計 2 回）。
BOTO_CONFIG = Config(
    connect_timeout=3,
    read_timeout=5,
    retries={"mode": "standard", "max_attempts": 1},
)


@cache
def client(service: str, region: str):
    """リージョンを明示してクライアントを返す（結果はキャッシュする）.

    素の boto3.client() を直接呼ぶと BOTO_CONFIG が効かないため、
    必ずこの関数を使うこと。
    """
    return boto3.client(service, region_name=region, config=BOTO_CONFIG)
