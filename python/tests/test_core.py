"""core のテスト.

AWS に依存しない純粋なロジック。例外の分類、複数項目の処理、設定の読み込み。
"""

from __future__ import annotations

import pytest
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

from dr_switch.core import (
    BaseConfig,
    ContinuableError,
    NotRecoverableError,
    RetryableError,
    classify,
    client,
    lambda_handler,
    optional,
    optional_json,
    raise_classified,
    required,
    run_per_item,
)
from tests.conftest import REGION, Context


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "test"}}, "Operation")


# --- classify --------------------------------------------------------------


@pytest.mark.parametrize("code", [
    "ThrottlingException", "Throttling", "SlowDown",
    "ProvisionedThroughputExceededException", "TooManyRequestsException",
    "InternalServerError", "ServiceUnavailable", "ConflictException",
    "TransactionInProgressException", "EC2ThrottledException",
])
def test_classify_retryable_codes(code):
    assert isinstance(
        classify(_client_error(code), best_effort=False, what="x"), RetryableError)


@pytest.mark.parametrize("exc", [
    EndpointConnectionError(endpoint_url="https://x"),
    ConnectTimeoutError(endpoint_url="https://x"),
    ReadTimeoutError(endpoint_url="https://x"),
])
def test_classify_connection_errors_are_retryable(exc):
    """接続系はエラーコードを持たないため、例外型で判定する."""
    assert isinstance(classify(exc, best_effort=False, what="x"), RetryableError)


def test_classify_permanent_error_with_best_effort():
    result = classify(_client_error("AccessDenied"), best_effort=True, what="x")
    assert isinstance(result, ContinuableError)


def test_classify_permanent_error_without_best_effort():
    """継続不可なら元の例外をそのまま返す（型を増やさない）."""
    original = _client_error("AccessDenied")
    assert classify(original, best_effort=False, what="x") is original


def test_raise_classified_raises_original():
    original = _client_error("AccessDenied")
    with pytest.raises(ClientError) as excinfo:
        raise_classified(original, best_effort=False, what="x")
    assert excinfo.value is original


def test_raise_classified_raises_converted():
    with pytest.raises(RetryableError):
        raise_classified(_client_error("SlowDown"), best_effort=False, what="x")


# --- run_per_item ----------------------------------------------------------


def test_run_per_item_all_succeed():
    result = run_per_item(["a", "b"], lambda k: {"ok": k},
                          best_effort=True, what="t")
    assert result == {"a": {"ok": "a"}, "b": {"ok": "b"}}


def test_run_per_item_aborts_on_connection_error():
    """エンドポイントに到達できない状態は項目に依存しない."""
    tried: list[str] = []

    def unreachable(key: str) -> dict:
        tried.append(key)
        raise EndpointConnectionError(endpoint_url="https://x")

    with pytest.raises(RetryableError):
        run_per_item(["a", "b", "c"], unreachable, best_effort=True, what="t")
    assert tried == ["a"]


def test_run_per_item_tries_all_on_item_error():
    tried: list[str] = []

    def fails_on_b(key: str) -> dict:
        tried.append(key)
        if key == "b":
            raise _client_error("ValidationException")
        return {"ok": key}

    with pytest.raises(ContinuableError):
        run_per_item(["a", "b", "c"], fails_on_b, best_effort=True, what="t")
    assert tried == ["a", "b", "c"]


def test_run_per_item_stops_on_permanent_error_without_best_effort():
    """継続不可の恒久エラーは集約せず即座に停止させる."""
    tried: list[str] = []

    def denied(key: str) -> dict:
        tried.append(key)
        raise _client_error("AccessDenied")

    with pytest.raises(ClientError):
        run_per_item(["a", "b"], denied, best_effort=False, what="t")
    assert tried == ["a"]


def test_run_per_item_retryable_wins_over_continuable():
    """一時エラーが混ざれば全体を再試行させる（操作は冪等）."""

    def mixed(key: str) -> dict:
        raise _client_error("SlowDown" if key == "a" else "ValidationException")

    with pytest.raises(RetryableError):
        run_per_item(["a", "b"], mixed, best_effort=True, what="t")


def test_run_per_item_with_empty_list():
    assert run_per_item([], lambda _k: {}, best_effort=True, what="t") == {}


# --- config ----------------------------------------------------------------


def test_required_raises_when_missing(monkeypatch):
    monkeypatch.delenv("NOT_SET", raising=False)
    with pytest.raises(KeyError, match="NOT_SET"):
        required("NOT_SET")


def test_required_returns_value(monkeypatch):
    monkeypatch.setenv("SET_VALUE", "v")
    assert required("SET_VALUE") == "v"


def test_optional_returns_default(monkeypatch):
    monkeypatch.delenv("NOT_SET", raising=False)
    assert optional("NOT_SET", "fallback") == "fallback"


def test_optional_json_parses(monkeypatch):
    monkeypatch.setenv("LIST_VALUE", '["a", "b"]')
    assert optional_json("LIST_VALUE", []) == ["a", "b"]


def test_optional_json_returns_default_when_empty(monkeypatch):
    monkeypatch.setenv("LIST_VALUE", "")
    assert optional_json("LIST_VALUE", ["default"]) == ["default"]


def test_base_config_from_env(monkeypatch):
    monkeypatch.setenv("REGION", REGION)
    assert BaseConfig.from_env().region == REGION


# --- client ----------------------------------------------------------------


def test_client_is_cached(monkeypatch):
    monkeypatch.setenv("REGION", REGION)
    assert client("sts", REGION) is client("sts", REGION)


def test_client_accepts_custom_config():
    """Config は同一性でハッシュされるため、定数を渡す前提."""
    custom = Config(connect_timeout=5, read_timeout=120,
                    retries={"mode": "standard", "max_attempts": 0})
    a = client("sts", REGION, custom)
    assert a is not client("sts", REGION)
    assert a.meta.config.read_timeout == 120


def test_client_uses_standard_retry_mode():
    """boto3 の既定はまだ非推奨の legacy なのでモードを明示している."""
    assert client("sts", REGION).meta.config.retries["mode"] == "standard"


# --- lambda_handler --------------------------------------------------------


def test_handler_returns_none_on_success(monkeypatch):
    monkeypatch.setenv("REGION", REGION)

    @lambda_handler("t-ok", BaseConfig)
    def ok(cfg, event, *, dry_run, context):
        return {}

    assert ok({}, Context()) is None


def test_handler_raises_retryable_on_problems(monkeypatch):
    monkeypatch.setenv("REGION", REGION)

    @lambda_handler("t-ng", BaseConfig)
    def not_ready(cfg, event, *, dry_run, context):
        return {"x": {"status": "CREATING"}}

    with pytest.raises(RetryableError, match="CREATING"):
        not_ready({}, Context())


def test_handler_classifies_throttling(monkeypatch):
    """観測系でもスロットリングがリトライになる（デコレータ統合の目的）."""
    monkeypatch.setenv("REGION", REGION)

    @lambda_handler("t-throttle", BaseConfig)
    def throttled(cfg, event, *, dry_run, context):
        raise _client_error("ThrottlingException")

    with pytest.raises(RetryableError):
        throttled({}, Context())


def test_handler_passes_dry_run(monkeypatch):
    monkeypatch.setenv("REGION", REGION)
    seen: dict = {}

    @lambda_handler("t-dry", BaseConfig)
    def record(cfg, event, *, dry_run, context):
        seen["dry_run"] = dry_run
        return {}

    record({"dry_run": True}, Context())
    assert seen["dry_run"] is True


def test_handler_lets_not_recoverable_through(monkeypatch):
    """ハンドラが自分で送出する NotRecoverableError は捕捉しない."""
    monkeypatch.setenv("REGION", REGION)

    @lambda_handler("t-fatal", BaseConfig)
    def fatal(cfg, event, *, dry_run, context):
        raise NotRecoverableError("stop")

    with pytest.raises(NotRecoverableError):
        fatal({}, Context())


def test_handler_lets_own_bug_through(monkeypatch):
    """AWS_ERRORS 以外（自分のコードのバグ）は素通しする."""
    monkeypatch.setenv("REGION", REGION)

    @lambda_handler("t-bug", BaseConfig)
    def buggy(cfg, event, *, dry_run, context):
        raise ValueError("bug")

    with pytest.raises(ValueError, match="bug"):
        buggy({}, Context())


def test_handler_exposes_wrapped(monkeypatch):
    """テストから中のロジックへ到達できる."""
    monkeypatch.setenv("REGION", REGION)

    @lambda_handler("t-wrapped", BaseConfig)
    def inner(cfg, event, *, dry_run, context):
        return {}

    assert inner.__wrapped__.__name__ == "inner"
