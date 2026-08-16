"""例外の分類と集約.

AWS の例外を 3 通りに振り分ける。再試行すべきもの（RetryableError）、
失敗したが処理を続けてよいもの（ContinuableError）、それ以外は分類せず
元の例外をそのまま送出する。

ハンドラが自分で判定する「待っても解消しない状態」には NotRecoverableError を使う。
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

# 再試行で解消しうるエラーコード。
#
# リトライは 2 層になっている。
#   SDK（botocore standard モード）… 個々の API 呼び出しを合計 3 回まで再送。
#                                     バックオフは一過性で約 75ms、
#                                     スロットリングで約 1.5 秒
#   呼び出し元（この分類）          … SDK が数回の短いバックオフで解消できな
#                                     かったものを、より長い間隔で再試行させる
# ここで分類するのは「SDK が諦めた後」の失敗であり、SDK のリトライとは
# 対象（1 呼び出し / 処理全体）も時間スケールも異なる。
#
# 分類の根拠は botocore の standard リトライモードの定義
# （botocore/retries/standard.py の ThrottledRetryableChecker.
# _THROTTLED_ERROR_CODES と TransientRetryableChecker._TRANSIENT_ERROR_CODES）。
# AWS SDK 自身が「再試行すべき」と判定しているコードそのもの。
#
# 「発生元」は各サービスの API モデル（botocore/data/<service>/*/service-2.json）
# が例外シェイプとして宣言しているものを確認した結果。query プロトコルの
# サービス（elbv2 / cloudwatch / sts）は汎用の Throttling を返すためモデルに
# 個別宣言がない。
#
# botocore のリストのうち BandwidthLimitExceeded は、ここで呼ぶどのサービスの
# モデルにも宣言が無いため含めていない。
RETRYABLE_CODES = frozenset({
    # --- スロットリング系（botocore: throttled） ---
    # 発生元: dynamodb / eks / scheduler
    "ThrottlingException",
    # 発生元: query プロトコルのサービス全般（elbv2 / cloudwatch / sts）
    "Throttling",
    "ThrottledException",
    "RequestThrottled",
    "RequestThrottledException",
    # 発生元: apigateway / lambda（HTTP 429）
    "TooManyRequestsException",
    # 発生元: dynamodb
    "RequestLimitExceeded",
    # 発生元: s3。リクエストレート急増時に 503 Slow Down を返す。AWS は
    # 「リクエストレートを維持し、指数バックオフで再試行する」ことを案内している
    "SlowDown",
    # 発生元: dynamodb（プロビジョンドキャパシティ超過）
    "ProvisionedThroughputExceededException",
    # 発生元: apigateway / dynamodb
    "LimitExceededException",
    # 発生元: dynamodb（同一項目への並行トランザクション）
    "TransactionInProgressException",
    # 発生元: lambda（VPC 内 ENI 作成のスロットリング）
    "EC2ThrottledException",

    # --- 一過性のサービス側エラー（botocore: transient） ---
    "RequestTimeout",
    "RequestTimeoutException",
    # botocore では throttled と transient の両方に含まれる
    "PriorRequestNotComplete",

    # --- botocore のリストには無いが、明示的に追加したもの ---
    # botocore は HTTP ステータス 500 / 502 / 503 / 504 で再試行を判定するため
    # コード名を持たない。こちらはコードを見て分類するので個別に列挙する。
    # 発生元: apigateway / eks（ServiceUnavailableException）、dynamodb
    # （InternalServerError）、lambda（ServiceException）、eks（ServerException）
    "ServiceUnavailable",
    "ServiceUnavailableException",
    "InternalFailure",
    "InternalServerError",
    "InternalServerErrorException",
    "ServiceException",
    "ServerException",
    # 発生元: apigateway / scheduler / cloudwatch。同一リソースへの並行更新で
    # 発生する。切替ワークフローは同じリソースを 1 回しか操作しないため通常は
    # 起きないが、再実行が重なった場合は時間をおけば解消する。
    # botocore は再試行対象としていないため、こちらの判断で追加している。
    "ConflictException",
})

class RetryableError(Exception):
    """時間をおいて再試行すれば解消しうる失敗、または未収束の状態。"""


class ContinuableError(Exception):
    """失敗したが、呼び出し元は処理を継続してよい。"""


class NotRecoverableError(Exception):
    """待っても解消しない状態を検出した。再試行せず止める.

    「まだ収束していない」（RetryableError）との区別が目的。Deployment の
    レプリカ数が足りないのは待てば揃うが、Lambda の State が Failed なのは
    待っても変わらない。後者を RetryableError にすると、解消しない状態を
    リトライ上限まで待ってから失敗することになり RTO を無駄にする。

    ハンドラが自分で判定して送出する。Retry にも Catch にもマッチしないので
    そのままワークフローが止まる。
    """


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

    例外は接続系エラー（TRANSIENT_ERRORS）のとき。エンドポイントに到達
    できない状態は項目に依存しないので、残りを試しても同じ結果になる。
    項目数ぶんタイムアウトを積み上げるだけなので中断する。
    """
    results: dict[str, dict] = {}
    errors: list[str] = []
    retryable = False

    for key in items:
        try:
            results[key] = fn(key)
        except TRANSIENT_ERRORS as exc:
            # エンドポイントに到達できない。残りの項目も同じ結果になるため、
            # 待ち時間を積み上げずに中断する。
            errors.append(f"{key}: {exc}")
            results[key] = {"error": str(exc)}
            raise classify(exc, best_effort=best_effort,
                           what=f"{what}({key})") from exc
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
