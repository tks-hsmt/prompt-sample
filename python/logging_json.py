"""構造化ログの設定.

ルートロガーに設定するため、ライブラリのログも同じ JSON 形式で出る。
"""

from __future__ import annotations

import json
import logging
import os
import sys

# logging が LogRecord に必ず載せる属性。これ以外は logger.info(..., extra=...)
# で渡された独自フィールドとみなす。record.extra という属性は作られないため、
# 差分を取る形で拾う必要がある。
_STANDARD_RECORD_ATTRS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
        "message", "asctime", "taskName"}

# ライブラリのログは既定で抑制する。botocore は INFO 以下が非常に多い。
LIBRARY_LOG_LEVEL = os.environ.get("LIBRARY_LOG_LEVEL", "WARNING")
APP_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        payload.update({key: value for key, value in vars(record).items()
                        if key not in _STANDARD_RECORD_ATTRS})
        return json.dumps(payload, ensure_ascii=False, default=str)


def _configure_root() -> None:
    """ルートロガーを JSON 出力に切り替える（アプリ・ライブラリ共通）."""
    root = logging.getLogger()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    # Lambda ランタイムが既定で付けるプレーンテキストのハンドラを置き換える
    root.handlers = [handler]
    root.setLevel(LIBRARY_LOG_LEVEL)


_configure_root()


def get_logger(name: str) -> logging.Logger:
    """アプリ用ロガー。出力はルートのハンドラに委ねる（propagate のまま）."""
    logger = logging.getLogger(name)
    logger.setLevel(APP_LOG_LEVEL)
    return logger
