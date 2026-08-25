"""apigateway ハンドラのテスト.

moto で API Gateway をシミュレートする。update_stage のスロットリング更新は
moto が実際に反映するため、「書いた値が読み戻せるか」まで検証できる。

apiStatus は moto が返さないため、バックエンドへ注入して検証する。
これは boto3 のモデルに apiStatus が存在することが前提（botocore 1.41.0 以上）。
"""

from __future__ import annotations

import json

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws
from moto.apigateway.models import RestAPI

from dr_switch.apigateway import handlers as ag
from dr_switch.core import (
    ContinuableError,
    NotRecoverableError,
    RetryableError,
)
from tests.conftest import REGION, Context

STAGE = "prod"


def _create_api(client) -> str:
    """デプロイ済みのステージを 1 つ持つ REST API を作る."""
    api_id = client.create_rest_api(name="test-api")["id"]
    root = client.get_resources(restApiId=api_id)["items"][0]["id"]
    client.put_method(restApiId=api_id, resourceId=root, httpMethod="GET",
                      authorizationType="NONE")
    client.put_integration(restApiId=api_id, resourceId=root, httpMethod="GET",
                           type="MOCK")
    client.create_deployment(restApiId=api_id, stageName=STAGE)
    return api_id


def _throttle(client, api_id: str) -> tuple[float | None, int | None]:
    stage = client.get_stage(restApiId=api_id, stageName=STAGE)
    settings = stage.get("methodSettings", {}).get("*/*")
    if not settings:
        return None, None
    return settings.get("throttlingRateLimit"), settings.get("throttlingBurstLimit")


@pytest.fixture
def api(env):
    """API を作り、環境変数を設定して ID を返す."""
    with mock_aws():
        client = boto3.client("apigateway", region_name=REGION)
        api_id = _create_api(client)
        env(REST_API_ID=api_id, STAGE=STAGE,
            THROTTLE_RATE="10000", THROTTLE_BURST="5000")
        yield api_id, client


# --- block -----------------------------------------------------------------


def test_block_sets_throttle_to_zero(api):
    api_id, client = api
    assert ag.block({}, Context()) is None
    assert _throttle(client, api_id) == (0.0, 0)


def test_block_is_idempotent(api):
    """既に 0 なら update_stage を呼ばない（呼んでも結果は同じ）."""
    api_id, client = api
    ag.block({}, Context())
    ag.block({}, Context())
    assert _throttle(client, api_id) == (0.0, 0)


def test_block_dry_run_does_not_change(api):
    api_id, client = api
    before = _throttle(client, api_id)
    ag.block({"dry_run": True}, Context())
    assert _throttle(client, api_id) == before


# --- enable ----------------------------------------------------------------


def test_enable_restores_configured_values(api):
    api_id, client = api
    ag.block({}, Context())
    assert ag.enable({}, Context()) is None
    assert _throttle(client, api_id) == (10000.0, 5000)


def test_enable_accepts_override(api):
    """入力で復元値を上書きできる."""
    api_id, client = api
    ag.block({}, Context())
    ag.enable({"throttle": {"rate": 500.0, "burst": 100}}, Context())
    assert _throttle(client, api_id) == (500.0, 100)


def test_enable_dry_run_does_not_change(api):
    api_id, client = api
    ag.block({}, Context())
    ag.enable({"dry_run": True}, Context())
    assert _throttle(client, api_id) == (0.0, 0)


# --- check -----------------------------------------------------------------


def test_check_passes_when_restored(api, monkeypatch):
    _stub_api_status(monkeypatch, "AVAILABLE")
    ag.block({}, Context())
    ag.enable({}, Context())
    assert ag.check({}, Context()) is None


def test_check_detects_unrestored_throttle(api, monkeypatch):
    _stub_api_status(monkeypatch, "AVAILABLE")
    ag.block({}, Context())
    with pytest.raises(RetryableError) as excinfo:
        ag.check({}, Context())
    detail = json.loads(str(excinfo.value))["apigateway-check"]["throttle"]
    assert detail["rate"] == 0.0
    assert detail["expected_rate"] == 10000.0


@pytest.mark.parametrize("status", ["AVAILABLE", "UPDATING"])
def test_check_accepts_healthy_api_status(api, monkeypatch, status):
    """UPDATING でも呼び出しは可能と公式に明記がある."""
    _stub_api_status(monkeypatch, status)
    ag.block({}, Context())
    ag.enable({}, Context())
    assert ag.check({}, Context()) is None


def test_check_retries_on_pending_api_status(api, monkeypatch):
    _stub_api_status(monkeypatch, "PENDING")
    ag.block({}, Context())
    ag.enable({}, Context())
    with pytest.raises(RetryableError) as excinfo:
        ag.check({}, Context())
    detail = json.loads(str(excinfo.value))["apigateway-check"]["api"]
    assert detail["api_status"] == "PENDING"


def test_check_stops_on_failed_api_status(api, monkeypatch):
    _stub_api_status(monkeypatch, "FAILED", message="boom")
    ag.block({}, Context())
    ag.enable({}, Context())
    with pytest.raises(NotRecoverableError) as excinfo:
        ag.check({}, Context())
    detail = json.loads(str(excinfo.value))["apigateway"]["api"]
    assert detail == {"api_status": "FAILED", "api_status_message": "boom"}


def test_check_skips_when_api_status_absent(api):
    """moto は apiStatus を返さない。取得できない場合は確認をスキップする.

    boto3 のバージョンが古いと同じ状態になるため、異常として扱わない。
    """
    ag.block({}, Context())
    ag.enable({}, Context())
    assert ag.check({}, Context()) is None


# --- 例外の分類 -------------------------------------------------------------


def test_block_continues_on_permanent_error(api, monkeypatch):
    """block は best_effort なので、恒久エラーでも ContinuableError になる."""
    def deny(*_args, **_kwargs):
        raise ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
            "GetStage")

    _, client = api
    monkeypatch.setattr(client, "get_stage", deny)
    monkeypatch.setattr(ag, "client", lambda *_a, **_k: client)
    with pytest.raises(ContinuableError):
        ag.block({}, Context())


def test_enable_stops_on_permanent_error(api, monkeypatch):
    """enable は best_effort=False なので、元の例外がそのまま出る."""

    def deny(*_args, **_kwargs):
        raise ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
            "GetStage")

    _, client = api
    monkeypatch.setattr(client, "get_stage", deny)
    monkeypatch.setattr(ag, "client", lambda *_a, **_k: client)
    with pytest.raises(ClientError):
        ag.enable({}, Context())


def test_throttling_becomes_retryable(api, monkeypatch):
    def throttled(*_args, **_kwargs):
        raise ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "slow down"}},
            "GetStage")

    _, client = api
    monkeypatch.setattr(client, "get_stage", throttled)
    monkeypatch.setattr(ag, "client", lambda *_a, **_k: client)
    with pytest.raises(RetryableError):
        ag.enable({}, Context())


# --- moto のカスタマイズ ----------------------------------------------------


def _stub_api_status(monkeypatch: pytest.MonkeyPatch, status: str,
                     message: str | None = None) -> None:
    """moto の RestAPI に apiStatus を持たせる.

    moto 5.2.3 の get_rest_api は apiStatus を返さない（実測で確認）。
    実環境の応答を再現するため、to_dict にフィールドを足す。

    boto3 側のモデルに apiStatus が無いとパース時に捨てられるので、
    このテストが通ること自体が botocore 1.41.0 以上であることの確認にもなる。
    """
    original = RestAPI.to_dict

    def patched(self: RestAPI) -> dict:
        result = original(self)
        result["apiStatus"] = status
        if message is not None:
            result["apiStatusMessage"] = message
        return result

    monkeypatch.setattr(RestAPI, "to_dict", patched)
