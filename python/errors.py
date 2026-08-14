"""例外の分類.

Step Functions が区別する必要があるのは 2 つだけ。

    RetryableError    一時的。または「まだ収束していない」  -> Retry
    ContinuableError  失敗したが作業継続してよい            -> Catch

それ以外の例外は型を定義せずそのまま送出する。Retry にも Catch にも
マッチしない例外は Step Functions がワークフローを失敗させるため、
「止める」ためだけの独自例外は不要。設定不備や権限不足はバグであり、
未捕捉例外として止まるのが正しい挙動。
"""

from __future__ import annotations

from typing import NoReturn

from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectionError,  # noqa: A004 - botocore の例外。組込み例外とは別物
    HTTPClientError,
)

from logging_json import get_logger

logger = get_logger(__name__)

Role = str  # "self" | "peer"

# boto3 が送出しうる例外の総称。これ以外（KeyError 等）は自分のコードの
# バグなので分類せず、そのまま送出させる。
AWS_ERRORS = (ClientError, BotoCoreError)

# ネットワーク起因の一過性エラー。エラーコードを持たないため
# RETRYABLE_CODES では拾えない。この 2 つが botocore の接続系例外の基底で、
# ConnectTimeoutError / ReadTimeoutError / EndpointConnectionError /
# ConnectionClosedError / ProxyConnectionError / SSLError を網羅する。
TRANSIENT_ERRORS = (ConnectionError, HTTPClientError)

RETRYABLE_CODES = frozenset({
    # スロットリング系。サービスごとにコードが違う点に注意
    # （S3 は SlowDown、DynamoDB は ProvisionedThroughputExceededException）
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
    """一時的な失敗、または「まだ収束していない」状態。SFN の Retry 対象。"""


class ContinuableError(Exception):
    """旧 ACTIVE 側の操作失敗。SFN の Catch で記録して続行する。

    リージョン障害中は PEER のコントロールプレーンが応答しないため、
    閉塞の失敗はワークフローを止めない。
    """


def classify(exc: Exception, *, role: Role, what: str) -> Exception:
    """AWS 例外を SFN が扱える形に振り分けて**返す**（送出はしない）.

    スロットリング・接続断・タイムアウト -> RetryableError
    PEER 側の恒久エラー                  -> ContinuableError（閉塞失敗は許容）
    SELF 側の恒久エラー                  -> 元の例外をそのまま返す（= 停止）

    送出せず返すのは、複数インスタンスをまとめて処理する run_per_item が
    「分類はしたいが今は送出したくない」ためで、入れ子の try/except を
    避けられる。単に送出したい場合は raise_classified() を使う。
    """
    code = ""
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")

    if isinstance(exc, TRANSIENT_ERRORS) or code in RETRYABLE_CODES:
        logger.warning("retryable error: %s: %s", what, exc)
        return RetryableError(f"{what}: {code or type(exc).__name__}: {exc}")

    if role == "peer":
        logger.warning("fencing failed, continuing: %s: %s", what, exc)
        return ContinuableError(f"{what}: {code or type(exc).__name__}: {exc}")

    logger.error("operation failed on new active region: %s: %s", what, exc)
    return exc


def raise_classified(exc: Exception, *, role: Role, what: str) -> NoReturn:
    """classify() の結果を送出する."""
    classified = classify(exc, role=role, what=what)
    if classified is exc:
        raise exc
    raise classified from exc
