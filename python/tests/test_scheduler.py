"""scheduler ハンドラのテスト.

moto は create_schedule / list_schedules / get_schedule_group を再現するため、
State の切り替えが実際に反映されるかまで検証できる。
"""

from __future__ import annotations

import json

import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from moto import mock_aws

from dr_switch.core import ContinuableError, NotRecoverableError, RetryableError
from dr_switch.scheduler import handlers as sc
from tests.conftest import ACCOUNT_ID, REGION, Context

GROUP = "dr-test-group"
ROLE = f"arn:aws:iam::{ACCOUNT_ID}:role/scheduler-target"
TARGET = f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:app"


def _create_schedule(client, name: str, state: str) -> None:
    client.create_schedule(
        Name=name,
        GroupName=GROUP,
        ScheduleExpression="rate(5 minutes)",
        State=state,
        FlexibleTimeWindow={"Mode": "OFF"},
        Target={"Arn": TARGET, "RoleArn": ROLE},
    )


def _states(client) -> dict[str, str]:
    return {
        s["Name"]: s["State"]
        for s in client.list_schedules(GroupName=GROUP)["Schedules"]
    }


@pytest.fixture
def scheduler(env):
    with mock_aws():
        client = boto3.client("scheduler", region_name=REGION)
        client.create_schedule_group(Name=GROUP)
        env(SCHEDULE_GROUP=GROUP)
        yield client


# --- block -----------------------------------------------------------------


def test_block_disables_all_schedules(scheduler):
    _create_schedule(scheduler, "s1", "ENABLED")
    _create_schedule(scheduler, "s2", "ENABLED")
    assert sc.block({}, Context()) is None
    assert _states(scheduler) == {"s1": "DISABLED", "s2": "DISABLED"}


def test_block_skips_already_disabled(scheduler):
    """一覧に State が含まれるので、冪等判定に get_schedule は不要."""
    _create_schedule(scheduler, "s1", "DISABLED")
    _create_schedule(scheduler, "s2", "ENABLED")
    sc.block({}, Context())
    assert _states(scheduler) == {"s1": "DISABLED", "s2": "DISABLED"}


def test_block_dry_run_does_not_change(scheduler):
    _create_schedule(scheduler, "s1", "ENABLED")
    sc.block({"dry_run": True}, Context())
    assert _states(scheduler) == {"s1": "ENABLED"}


def test_block_with_no_schedules(scheduler):
    """グループが空でも成功する."""
    assert sc.block({}, Context()) is None


# --- enable ----------------------------------------------------------------


def test_enable_enables_all_schedules(scheduler):
    _create_schedule(scheduler, "s1", "DISABLED")
    _create_schedule(scheduler, "s2", "DISABLED")
    assert sc.enable({}, Context()) is None
    assert _states(scheduler) == {"s1": "ENABLED", "s2": "ENABLED"}


def test_enable_preserves_target(scheduler):
    """UpdateSchedule は全パラメータを要求する。Target が消えないこと."""
    _create_schedule(scheduler, "s1", "DISABLED")
    sc.enable({}, Context())
    got = scheduler.get_schedule(Name="s1", GroupName=GROUP)
    assert got["Target"]["Arn"] == TARGET
    assert got["Target"]["RoleArn"] == ROLE
    assert got["ScheduleExpression"] == "rate(5 minutes)"


def test_enable_dry_run_does_not_change(scheduler):
    _create_schedule(scheduler, "s1", "DISABLED")
    sc.enable({"dry_run": True}, Context())
    assert _states(scheduler) == {"s1": "DISABLED"}


# --- check -----------------------------------------------------------------


def test_check_passes_when_all_enabled(scheduler):
    _create_schedule(scheduler, "s1", "ENABLED")
    assert sc.check({}, Context()) is None


def test_check_detects_disabled_schedule(scheduler):
    _create_schedule(scheduler, "s1", "ENABLED")
    _create_schedule(scheduler, "s2", "DISABLED")
    with pytest.raises(RetryableError) as excinfo:
        sc.check({}, Context())
    detail = json.loads(str(excinfo.value))["scheduler-check"]
    assert detail["not_enabled"] == ["s2"]


def test_check_stops_when_group_is_deleting(scheduler, monkeypatch):
    """ScheduleGroupState が DELETING なら待っても戻らない."""
    _create_schedule(scheduler, "s1", "ENABLED")
    original = scheduler.get_schedule_group

    def deleting(**kwargs):
        return {**original(**kwargs), "State": "DELETING"}

    monkeypatch.setattr(scheduler, "get_schedule_group", deleting)
    monkeypatch.setattr(sc, "client", lambda *_a, **_k: scheduler)
    with pytest.raises(NotRecoverableError) as excinfo:
        sc.check({}, Context())
    detail = json.loads(str(excinfo.value))["scheduler"][GROUP]
    assert detail["group_state"] == "DELETING"


# --- 例外の分類 -------------------------------------------------------------


def test_block_continues_on_permanent_error(scheduler, monkeypatch):
    """block は best_effort。1 件が恒久エラーでも ContinuableError で終わる."""
    _create_schedule(scheduler, "s1", "ENABLED")

    def deny(**_kwargs):
        raise ClientError(
            {"Error": {"Code": "ValidationException", "Message": "bad"}},
            "UpdateSchedule")

    monkeypatch.setattr(scheduler, "update_schedule", deny)
    monkeypatch.setattr(sc, "client", lambda *_a, **_k: scheduler)
    with pytest.raises(ContinuableError):
        sc.block({}, Context())


def test_enable_stops_on_permanent_error(scheduler, monkeypatch):
    """enable は best_effort=False。恒久エラーはそのまま送出される."""
    _create_schedule(scheduler, "s1", "DISABLED")

    def deny(**_kwargs):
        raise ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
            "UpdateSchedule")

    monkeypatch.setattr(scheduler, "update_schedule", deny)
    monkeypatch.setattr(sc, "client", lambda *_a, **_k: scheduler)
    with pytest.raises(ClientError):
        sc.enable({}, Context())


def test_run_per_item_aborts_on_connection_error(scheduler, monkeypatch):
    """接続系は残りを試さず中断する。到達不能なら結果が同じため."""
    for name in ("s1", "s2", "s3"):
        _create_schedule(scheduler, name, "ENABLED")

    calls: list[str] = []

    def unreachable(**kwargs):
        calls.append(kwargs["Name"])
        raise EndpointConnectionError(endpoint_url="https://scheduler")

    monkeypatch.setattr(scheduler, "get_schedule", unreachable)
    monkeypatch.setattr(sc, "client", lambda *_a, **_k: scheduler)
    with pytest.raises(RetryableError):
        sc.block({}, Context())
    assert len(calls) == 1


def test_run_per_item_tries_all_on_item_error(scheduler, monkeypatch):
    """項目ごとのエラーは全件試行して集約する."""
    for name in ("s1", "s2", "s3"):
        _create_schedule(scheduler, name, "ENABLED")

    calls: list[str] = []
    original = scheduler.update_schedule

    def sometimes_fails(**kwargs):
        calls.append(kwargs["Name"])
        if kwargs["Name"] == "s2":
            raise ClientError(
                {"Error": {"Code": "ValidationException", "Message": "bad"}},
                "UpdateSchedule")
        return original(**kwargs)

    monkeypatch.setattr(scheduler, "update_schedule", sometimes_fails)
    monkeypatch.setattr(sc, "client", lambda *_a, **_k: scheduler)
    with pytest.raises(ContinuableError):
        sc.block({}, Context())
    assert sorted(calls) == ["s1", "s2", "s3"]
