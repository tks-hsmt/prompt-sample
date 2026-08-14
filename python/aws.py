"""boto3 クライアントの生成方針."""

from __future__ import annotations

from functools import cache

import boto3
from botocore.config import Config

# 外部呼び出しのタイムアウトとリトライ。
#   - 既定の 60 秒では、応答しない相手を待つだけで RTO を消費する
#   - botocore 内部のリトライは最小限にし、再試行は Step Functions の Retry に
#     任せる（実行履歴に残り、待機時間を宣言で制御できるため）
#   - max_attempts は「リトライ回数」であり総試行回数ではない。1 を指定すると
#     初回 + リトライ 1 回 = 合計 2 回になる
#   - 最悪時間 = (connect + read) * 合計試行回数 = (3 + 5) * 2 = 16 秒 / API 呼び出し
BOTO_CONFIG = Config(
    connect_timeout=3,
    read_timeout=5,
    retries={"mode": "standard", "max_attempts": 1},
)


@cache
def client(service: str, region: str):
    """リージョンを必ず明示する。デフォルトリージョン依存は事故の元。

    タイムアウトとリトライは BOTO_CONFIG で明示する。素の boto3.client() を
    直接呼ぶと既定の 60 秒が効いてしまうため、必ずこの関数を使うこと。
    ウォームスタート時にクライアントを再利用するためキャッシュする。
    """
    return boto3.client(service, region_name=region, config=BOTO_CONFIG)
