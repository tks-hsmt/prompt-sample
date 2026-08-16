"""例外の分類と集約.

AWS の例外を 3 通りに振り分ける。再試行すべきもの（RetryableError）、
失敗したが処理を続けてよいもの（ContinuableError）、それ以外は分類せず
元の例外をそのまま送出する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, NoReturn

from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectionError,  # noqa: A004 - botocore の例外。組込み例外とは別物
    HTTPClientError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# boto3 が送出しうる例外の総称。これ以外は分類せずそのまま送出させる。
AWS_ERRORS = (ClientError, BotoCoreError)

# ネットワーク起因の一過性エラー。エラーコードを持たないため
# RETRYABLE_CODES では拾えない。この 2 つが botocore の接続系例外の基底。
TRANSIENT_ERRORS = (ConnectionError, HTTPClientError)

RETRYABLE_CODES = frozenset({
    # スロットリング系。サービスごとにコードが異なる
    "ThrottlingException",
    "Throttling",
    "ThrottledException",
    "TooManyRequestsException",
    "RequestLimitExceeded",
    "RequestThrottled",
    "RequestThrottledException",
    "SlowDown",
    "ProvisionedThroughputExceededException",
    # 一過性のサービス側エラー
    "ServiceUnavailable",
    "ServiceUnavailableException",
    "InternalFailure",
    "InternalServerError",
    "InternalServerErrorException",
    "LimitExceededException",
    "ConflictException",
    "RequestTimeout",
    "RequestTimeoutException",
    "PriorRequestNotComplete",
})


class RetryableError(Exception):
    """時間をおいて再試行すれば解消しうる失敗、または未収束の状態。"""


class ContinuableError(Exception):
    """失敗したが、呼び出し元は処理を継続してよい。"""


def classify(exc: Exception, *, best_effort: bool, what: str) -> Exception:
    """AWS 例外を分類して返す（送出はしない）.

    スロットリング・接続断・タイムアウト -> RetryableError
    恒久エラー かつ best_effort          -> ContinuableError
    恒久エラー かつ not best_effort      -> 元の例外をそのまま返す

    best_effort は操作の性質。失敗しても処理を続けてよい操作なら True。

    送出したい場合は raise_classified() を使う。
    """
    code = ""
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")

    if isinstance(exc, TRANSIENT_ERRORS) or code in RETRYABLE_CODES:
        logger.warning("retryable error: %s: %s", what, exc)
        return RetryableError(f"{what}: {code or type(exc).__name__}: {exc}")

    if best_effort:
        logger.warning("best-effort operation failed, continuing: %s: %s",
                       what, exc)
        return ContinuableError(f"{what}: {code or type(exc).__name__}: {exc}")

    logger.error("operation failed: %s: %s", what, exc)
    return exc


def raise_classified(exc: Exception, *, best_effort: bool, what: str) -> NoReturn:
    """classify() の結果を送出する."""
    classified = classify(exc, best_effort=best_effort, what=what)
    if classified is exc:
        raise exc
    raise classified from exc


def run_per_item(items: list[str], fn: Callable[[str], dict], *,
                 best_effort: bool, what: str) -> dict[str, dict]:
    """複数インスタンスを独立に処理する。1 件失敗しても残りを必ず試みる.

    途中で中断すると、止められたはずの残りが開いたまま残るため。
    """
    results: dict[str, dict] = {}
    errors: list[str] = []
    retryable = False

    for key in items:
        try:
            results[key] = fn(key)
        except AWS_ERRORS as exc:
            classified = classify(exc, best_effort=best_effort,
                                  what=f"{what}({key})")
            if not isinstance(classified, RetryableError | ContinuableError):
                # 継続不可の恒久エラー。集約せず即座に停止させる。
                raise classified from exc
            retryable = retryable or isinstance(classified, RetryableError)
            errors.append(f"{key}: {classified}")
            results[key] = {"error": str(classified)}

    if errors:
        message = "; ".join(errors)
        # 一時エラーが混ざれば全体を再試行させる（操作は冪等）
        raise (RetryableError if retryable else ContinuableError)(message)

    return results
