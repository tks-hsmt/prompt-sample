"""Lambda 統合（任意導入）。

Lambda 実行時のコンテキスト（リクエスト ID・コールドスタート・関数名など）を
全ログ行へ自動付与するデコレータとフィルタを提供する。

コンテキストの保持にはモジュールグローバルを用いる。Python ではデフォルト Lambda も
Managed Instances も呼び出しがプロセス単位で分離されるため、グローバルは呼び出し間で
競合せず、ハンドラ内のワーカースレッドからも参照できる。
"""

from __future__ import annotations

import functools
import logging
from typing import Callable, Optional, Tuple

# 処理中の呼び出しに紐づくログ用コンテキスト。呼び出しごとに置き換える。
_invocation_context: dict[str, object] = {}

# init は実行環境ごとに 1 回だけ走るため、初回呼び出しの判定に使える。
_is_cold_start: bool = True

_filter_installed: bool = False


class _LambdaContextFilter(logging.Filter):
    """``_invocation_context`` の各項目をログレコードへ属性として付与するフィルタ。

    付与した属性は ``JsonLogFormatter`` が JSON のフィールドとして出力する。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in _invocation_context.items():
            setattr(record, key, value)
        return True  # レコードは破棄せず常に通す（属性付与が目的）


def _ensure_filter_installed() -> None:
    """ルートロガーの各ハンドラへフィルタを一度だけ取り付ける。

    初回呼び出し時に遅延実行することで ``setup_logging()`` との import 順に依存しない。
    """
    global _filter_installed
    if _filter_installed:
        return
    # 子ロガーから伝播するレコードも拾うため、ロガーでなくハンドラに付ける。
    context_filter = _LambdaContextFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(context_filter)
    _filter_installed = True


def inject_lambda_context(
    handler: Optional[Callable] = None,
    *,
    fields: Tuple[str, ...] = ("requestId", "functionName", "coldStart"),
) -> Callable:
    """Lambda ハンドラに付与し、呼び出しコンテキストを全ログへ自動注入するデコレータ。

    ``@inject_lambda_context`` と ``@inject_lambda_context(fields=(...))`` の両形式で使える。

    Args:
        handler: デコレート対象の Lambda ハンドラ。引数なし使用時は None。
        fields: 出力へ含める項目。"requestId" / "functionName" /
            "functionVersion" / "memoryLimitMB" / "coldStart" から選ぶ。

    Returns:
        Callable: ラップ済みハンドラ（引数あり呼び出し時はデコレータ本体）。
    
    Example:
        import logging
        from common_logger import setup_logging, inject_lambda_context, log_extra, logtypes

        setup_logging()
        logger = logging.getLogger()

        @inject_lambda_context
        def lambda_handler(event, context):
            logging.error("message", extra=log_extra(logtypes.LOG_TYPE_S3_ERROR))
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(event, context):
            global _is_cold_start, _invocation_context

            _ensure_filter_installed()

            # ローカルテスト等で属性が欠けても落ちないよう getattr で取得する。
            data: dict[str, object] = {}
            if "requestId" in fields:
                data["requestId"] = getattr(context, "aws_request_id", "")
            if "functionName" in fields:
                data["functionName"] = getattr(context, "function_name", "")
            if "functionVersion" in fields:
                data["functionVersion"] = getattr(context, "function_version", "")
            if "memoryLimitMB" in fields:
                data["memoryLimitMB"] = getattr(context, "memory_limit_in_mb", "")
            if "coldStart" in fields:
                data["coldStart"] = _is_cold_start

            _invocation_context = data  # 単一代入で置き換える（途中の空状態を作らない）
            _is_cold_start = False

            return func(event, context)

        return wrapper

    # 引数あり/なしの両方の呼び出し形式に対応する。
    return decorator(handler) if handler is not None else decorator