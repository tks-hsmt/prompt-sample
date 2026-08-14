"""ハンドラのデコレータと、複数インスタンスをまとめて処理するヘルパ.

SELF = 自リージョン = これから ACTIVE になる側 = 開放する対象
PEER = 相手リージョン = これまで ACTIVE だった側 = 閉塞する対象
"""

from __future__ import annotations

import functools
import json
from typing import TYPE_CHECKING, Any

from config import BaseConfig, Role
from errors import (
    AWS_ERRORS,
    ContinuableError,
    RetryableError,
    classify,
    raise_classified,
)
from logging_json import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger(__name__)


def run_per_item(items: list[str], fn: Callable[[str], dict], *,
                 role: Role, what: str) -> dict[str, dict]:
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
            classified = classify(exc, role=role, what=f"{what}({key})")
            if not isinstance(classified, RetryableError | ContinuableError):
                # SELF 側の恒久エラー。集約せず即座に停止させる。
                raise classified from exc
            retryable = retryable or isinstance(classified, RetryableError)
            errors.append(f"{key}: {classified}")
            results[key] = {"error": str(classified)}

    if errors:
        message = "; ".join(errors)
        # 一時エラーが混ざれば全体を再試行させる（操作は冪等）
        raise (RetryableError if retryable else ContinuableError)(message)

    return results


def ops_handler(action: str, config_cls: type[BaseConfig]) -> Callable:
    """操作系ハンドラ用。role の解決・設定読み込み・ログ・応答整形・
    AWS 例外の分類を担う.

    デコレートされる関数のシグネチャ:
        fn(cfg: <ConfigCls>, event: dict, *, dry_run: bool, context) -> dict

    AWS 例外の捕捉はここだけに置く。個々の操作側では書かない。
    AWS_ERRORS 以外（自分のコードのバグ）と、run_per_item が送出する
    RetryableError / ContinuableError は捕捉せず素通しする。
    """

    def decorator(fn: Callable[..., dict]) -> Callable[[dict, Any], dict]:
        @functools.wraps(fn)
        def wrapper(event: dict, context) -> dict:
            role: Role = event["role"]
            dry_run = bool(event.get("dry_run", False))
            cfg = config_cls.from_env(role)
            logger.info("%s start: role=%s region=%s dry_run=%s",
                        action, role, cfg.region, dry_run)
            try:
                result = fn(cfg, event, dry_run=dry_run, context=context)
            except AWS_ERRORS as exc:
                raise_classified(exc, role=cfg.role,
                                 what=f"{action}({cfg.role}:{cfg.region})")
            logger.info("%s done: %s", action, json.dumps(result, default=str))
            return {"action": action, "role": role,
                    "region": cfg.region, "dry_run": dry_run, **result}

        return wrapper

    return decorator


def check_handler(name: str, config_cls: type[BaseConfig]) -> Callable:
    """観測系ハンドラ用。SELF 固定で実行し、未収束なら RetryableError を送出.

    デコレートされる関数のシグネチャ:
        fn(cfg: <ConfigCls>) -> dict   # 問題のある項目だけを返す。正常なら {}

    AWS API のエラーは捕捉せず素通しする。
    """

    def decorator(fn: Callable[[Any], dict]) -> Callable[[dict, Any], None]:
        @functools.wraps(fn)
        def wrapper(event: dict, context) -> None:
            cfg = config_cls.from_env("self")
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
