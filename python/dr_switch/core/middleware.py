"""ハンドラを包むデコレータ.

設定の読み込みと AWS 例外の分類を引き受ける。
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


def lambda_handler(action: str, config_cls: type[BaseConfig], *,
                   best_effort: bool = False) -> Callable:
    """ハンドラの契約を実装する.

        成功                    -> 何も返さない
        一時的な失敗・未収束    -> RetryableError
        継続してよい失敗        -> ContinuableError
        それ以外                -> 元の例外をそのまま送出

    呼び出し元は例外の有無だけで判断する。何をしたかは返さない
    （実行前から決まっているうえ、参照されないため）。

    デコレートされる関数のシグネチャ:
        fn(cfg: <ConfigCls>, event: dict, *, dry_run: bool, context) -> dict

    戻り値は「問題のある項目」だけを表す。空なら成功。非空なら
    RetryableError に載せて送出する。処理を実行するだけの関数は
    常に空を返す。

    best_effort は操作の性質。失敗しても処理を続けてよい操作なら True。

    AWS 例外の捕捉はここだけに置く。AWS_ERRORS 以外（自分のコードのバグ）と、
    run_per_item が送出する RetryableError / ContinuableError は
    捕捉せず素通しする。
    """

    def decorator(fn: Callable[..., dict]) -> Callable[[dict, Any], None]:
        @functools.wraps(fn)
        def wrapper(event: dict, context) -> None:
            dry_run = bool(event.get("dry_run", False))
            cfg = config_cls.from_env()
            logger.info("%s start: region=%s dry_run=%s",
                        action, cfg.region, dry_run)

            try:
                problems = fn(cfg, event, dry_run=dry_run, context=context)
            except AWS_ERRORS as exc:
                raise_classified(exc, best_effort=best_effort,
                                 what=f"{action}({cfg.region})")

            if problems:
                message = json.dumps({action: problems}, ensure_ascii=False,
                                     default=str)
                logger.warning("%s not ready: %s", action, message)
                raise RetryableError(message)

            logger.info("%s done: region=%s", action, cfg.region)

        return wrapper

    return decorator
