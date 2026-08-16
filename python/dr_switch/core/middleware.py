"""ハンドラを包むデコレータ.

設定の読み込み、ログ、応答の整形、例外の分類を引き受ける。
対象リージョンは環境変数で決まるため、ここでは判断しない。

ログの初期化と呼び出しコンテキストの注入は共通モジュールの
`inject_lambda_context` が担うため、ここでは扱わない。
"""

from __future__ import annotations

import functools
import json
import logging
from typing import TYPE_CHECKING, Any

from dr_switch.core.errors import AWS_ERRORS, RetryableError, raise_classified

if TYPE_CHECKING:
    from collections.abc import Callable

    from dr_switch.core.config import BaseConfig

logger = logging.getLogger(__name__)


def ops_handler(action: str, config_cls: type[BaseConfig], *,
                best_effort: bool) -> Callable:
    """操作系ハンドラ用。設定読み込み・ログ・応答整形・AWS 例外の分類を担う.

    best_effort は操作の性質。失敗しても処理を続けてよい操作なら True。

    デコレートされる関数のシグネチャ:
        fn(cfg: <ConfigCls>, event: dict, *, dry_run: bool, context) -> dict

    AWS 例外の捕捉はここだけに置く。個々の操作側では書かない。
    AWS_ERRORS 以外（自分のコードのバグ）と、run_per_item が送出する
    RetryableError / ContinuableError は捕捉せず素通しする。
    """

    def decorator(fn: Callable[..., dict]) -> Callable[[dict, Any], dict]:
        @functools.wraps(fn)
        def wrapper(event: dict, context) -> dict:
            dry_run = bool(event.get("dry_run", False))
            cfg = config_cls.from_env()
            logger.info("%s start: region=%s dry_run=%s",
                        action, cfg.region, dry_run)
            try:
                result = fn(cfg, event, dry_run=dry_run, context=context)
            except AWS_ERRORS as exc:
                raise_classified(exc, best_effort=best_effort,
                                 what=f"{action}({cfg.region})")
            logger.info("%s done: %s", action, json.dumps(result, default=str))
            return {"action": action, "region": cfg.region,
                    "dry_run": dry_run, **result}

        return wrapper

    return decorator


def check_handler(name: str, config_cls: type[BaseConfig]) -> Callable:
    """観測系ハンドラ用。未収束なら RetryableError を送出.

    デコレートされる関数のシグネチャ:
        fn(cfg: <ConfigCls>) -> dict   # 問題のある項目だけを返す。正常なら {}

    AWS API のエラーは捕捉せず素通しする。
    """

    def decorator(fn: Callable[[Any], dict]) -> Callable[[dict, Any], None]:
        @functools.wraps(fn)
        def wrapper(event: dict, context) -> None:
            cfg = config_cls.from_env()
            logger.info("check %s start: region=%s", name, cfg.region)
            problems = fn(cfg)
            if problems:
                message = json.dumps({name: problems}, ensure_ascii=False,
                                     default=str)
                logger.warning("check %s not ready: %s", name, message)
                raise RetryableError(message)
            logger.info("check %s ok: region=%s", name, cfg.region)

        return wrapper

    return decorator
