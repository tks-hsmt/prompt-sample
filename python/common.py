"""DR 切替 Lambda 共通モジュール.

配置方針:
    東京・大阪の両リージョンに同一構成をデプロイする。
    実行するのは常に「これから ACTIVE になる側」のリージョン。
        東京 -> 大阪の切替  : 大阪の Step Functions / Lambda が動く
        大阪 -> 東京の切戻し: 東京の Step Functions / Lambda が動く

    したがって各 Lambda から見て
        SELF = 自リージョン = これから ACTIVE になる側 = 開放する対象
        PEER = 相手リージョン = これまで ACTIVE だった側 = 閉塞する対象
    となり、切替方向は「どのリージョンの Step Functions を叩いたか」で
    一意に決まる。入力に direction を持たせない（取り違え事故が起きない）。

エラー処理の契約:
    Step Functions が区別する必要があるのは 2 つだけ。

        RetryableError    一時的。待てば直る          -> Retry
        ContinuableError  失敗したが作業継続してよい  -> Catch

    それ以外の例外は型を定義せずそのまま送出する。Retry にも Catch にも
    マッチしない例外は Step Functions がワークフローを失敗させるため、
    「止める」ためだけの独自例外は不要。設定不備や権限不足はバグであり、
    未捕捉例外として止まるのが正しい挙動。
"""

from __future__ import annotations

import functools
import json
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from typing import Any, Literal, NoReturn

import boto3
from botocore.exceptions import BotoCoreError, ClientError

Role = Literal["self", "peer"]

# boto3 が送出しうる例外の総称。これ以外（KeyError 等）は自分のコードの
# バグなので分類せず、そのまま送出させる。
AWS_ERRORS = (ClientError, BotoCoreError)


class _JsonFormatter(logging.Formatter):
    """コンテナイメージデプロイのため Layer が使えず、ランタイムのログ形式
    設定にも依存しないよう、フォーマッタを自前で持つ。
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra", None)
        if extra:
            payload.update(extra)
        return json.dumps(payload, ensure_ascii=False)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
    return logger


logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# 例外
# ---------------------------------------------------------------------------


class RetryableError(Exception):
    """一時的な失敗、または「まだ収束していない」状態。SFN の Retry 対象。"""


class ContinuableError(Exception):
    """旧 ACTIVE 側の操作失敗。SFN の Catch で記録して続行する。

    リージョン障害中は PEER のコントロールプレーンが応答しないため、
    閉塞の失敗はワークフローを止めない。
    """


RETRYABLE_CODES = frozenset({
    "ThrottlingException",
    "Throttling",
    "TooManyRequestsException",
    "RequestLimitExceeded",
    "ServiceUnavailable",
    "InternalFailure",
    "InternalServerError",
    "InternalServerErrorException",
    "LimitExceededException",
    "ConflictException",
})


def raise_classified(exc: Exception, *, role: Role, what: str) -> NoReturn:
    """AWS 例外を SFN が扱える形に振り分けて送出する.

    スロットリング等   -> RetryableError
    PEER 側の恒久エラー -> ContinuableError（閉塞失敗は許容する）
    SELF 側の恒久エラー -> 元の例外をそのまま送出（未捕捉 = ワークフロー停止）
    """
    code = ""
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")

    if code in RETRYABLE_CODES:
        logger.warning("retryable error: %s: %s", what, exc)
        raise RetryableError(f"{what}: {code}: {exc}") from exc

    if role == "peer":
        logger.warning("fencing failed, continuing: %s: %s", what, exc)
        raise ContinuableError(f"{what}: {code or type(exc).__name__}: {exc}") from exc

    logger.error("operation failed on new active region: %s: %s", what, exc)
    # 元の例外をそのまま送出する。裸の raise は except ブロック内でしか
    # 動かず、呼び出し側の例外コンテキストに暗黙依存するため使わない。
    raise exc


# ---------------------------------------------------------------------------
# 設定（環境変数）
# ---------------------------------------------------------------------------


def _env(role: Role, key: str, default: str | None = None) -> str:
    name = f"{role.upper()}_{key}"
    value = os.environ.get(name, default)
    if value is None:
        raise KeyError(f"environment variable not set: {name}")
    return value


def _env_json(role: Role, key: str, default: Any) -> Any:
    raw = os.environ.get(f"{role.upper()}_{key}")
    return json.loads(raw) if raw else default


@dataclass(frozen=True)
class RegionConfig:
    """片側リージョンの設定。属性アクセスなのでタイポが早期に露見する。"""

    role: Role
    region: str
    rest_api_id: str = ""
    stage: str = ""
    health_url: str | None = None
    schedule_group: str = "default"
    function_names: list[str] = field(default_factory=list)
    table_names: list[str] = field(default_factory=list)
    target_group_arns: list[str] = field(default_factory=list)
    alarm_prefix: str = ""
    eks_cluster_name: str = ""
    # 確認対象の namespace。Deployment 名と必要数はクラスタから読むため不要。
    eks_namespaces: list[str] = field(default_factory=list)
    hybrid_node_selector: str = "eks.amazonaws.com/compute-type=hybrid"
    replication_buckets: list[str] = field(default_factory=list)


def config(role: Role) -> RegionConfig:
    return RegionConfig(
        role=role,
        region=_env(role, "REGION"),
        rest_api_id=_env(role, "REST_API_ID", ""),
        stage=_env(role, "STAGE", ""),
        health_url=os.environ.get(f"{role.upper()}_HEALTH_URL"),
        schedule_group=_env(role, "SCHEDULE_GROUP", "default"),
        function_names=_env_json(role, "FUNCTION_NAMES", []),
        table_names=_env_json(role, "TABLE_NAMES", []),
        target_group_arns=_env_json(role, "TARGET_GROUP_ARNS", []),
        alarm_prefix=_env(role, "ALARM_PREFIX", ""),
        eks_cluster_name=_env(role, "EKS_CLUSTER_NAME", ""),
        eks_namespaces=_env_json(role, "EKS_NAMESPACES", []),
        hybrid_node_selector=_env(
            role, "HYBRID_NODE_SELECTOR", "eks.amazonaws.com/compute-type=hybrid"),
        replication_buckets=_env_json(role, "REPLICATION_BUCKETS", []),
    )


@cache
def client(service: str, region: str):
    """リージョンを必ず明示する。デフォルトリージョン依存は事故の元。

    ウォームスタート時にクライアントを再利用するためキャッシュする。
    """
    return boto3.client(service, region_name=region)


# ---------------------------------------------------------------------------
# ハンドラのデコレータ（横断的関心事）
# ---------------------------------------------------------------------------


def run_per_item(items: list[str], fn: Callable[[str], dict], *,
                 role: Role, what: str) -> dict[str, dict]:
    """複数インスタンスを独立に処理する。1 件失敗しても残りを必ず試みる.

    操作系の Lambda は「リソース種別」を担当し、その中の個別インスタンス
    （バケット、スケジュール）はループで処理する。ここで最初の失敗により
    中断すると、止められたはずの残りが開いたままになる。閉塞では止められた
    分だけリスクが減るため、部分的な成功に価値がある。

    role=self の恒久エラーは raise_classified が元の例外をそのまま送出する
    ため、下の except には捕まらず即座に停止する（意図通り）。
    """
    results: dict[str, dict] = {}
    errors: list[str] = []
    retryable = False

    for key in items:
        try:
            results[key] = fn(key)
        except AWS_ERRORS as exc:
            try:
                raise_classified(exc, role=role, what=f"{what}({key})")
            except RetryableError as classified:
                retryable = True
                errors.append(f"{key}: {classified}")
            except ContinuableError as classified:
                errors.append(f"{key}: {classified}")
            results[key] = {"error": errors[-1]}

    if errors:
        message = "; ".join(errors)
        # 一時エラーが 1 つでもあれば全体を再試行させる。操作は冪等。
        raise (RetryableError if retryable else ContinuableError)(message)

    return results


def ops_handler(action: str) -> Callable:
    """操作系ハンドラ用。role の解決・設定読み込み・ログ・応答整形・
    AWS 例外の分類を担う.

    デコレートされる関数のシグネチャ:
        fn(cfg: RegionConfig, event: dict, *, dry_run: bool, context) -> dict

    AWS 例外の捕捉をここに集約している理由:
        分類の判断材料はエラーコードと role の 2 つで、どちらもこの
        デコレータが持っている。個々の操作側で捕捉しても情報を足せず、
        catch-and-rethrow になるだけ。さらに操作系を追加した人が
        try/except を書き忘れると、PEER 側の恒久エラーが
        ContinuableError にならずワークフローを止めてしまう。
        ここに集約すればその失敗モード自体が消える。

        AWS_ERRORS 以外（KeyError 等、自分のコードのバグ）は捕捉しない。
        RetryableError / ContinuableError も AWS_ERRORS ではないので、
        個別に集約の意味論を持つ関数（s3_replication）が自前で送出した
        ものはここを素通りする。二重処理にならない。
    """

    def decorator(fn: Callable[..., dict]) -> Callable[[dict, Any], dict]:
        @functools.wraps(fn)
        def wrapper(event: dict, context) -> dict:
            role: Role = event["role"]
            dry_run = bool(event.get("dry_run", False))
            cfg = config(role)
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


def check_handler(name: str) -> Callable:
    """観測系ハンドラ用。SELF 固定で実行し、未収束なら RetryableError を送出.

    デコレートされる関数のシグネチャ:
        fn(cfg: RegionConfig) -> dict   # 「問題のある項目」だけを返す

    正常時は何も返さない。問題があった項目だけを例外に載せるため、
    項目ごとの ok フラグは持たない（例外に載る = NG が自明）。
    AWS API のエラーは握りつぶさず素通しさせる。権限不足やリソース不在は
    バグであり、待っても直らないので止まるのが正しい。
    """

    def decorator(fn: Callable[[RegionConfig], dict]) -> Callable[[dict, Any], None]:
        @functools.wraps(fn)
        def wrapper(event: dict, context) -> None:
            cfg = config("self")
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
