"""s3 ハンドラのテスト.

moto はレプリケーション設定を保持するため、Status の切り替えが反映されるかを
検証できる。滞留の確認は CloudWatch のメトリクスを見るので、moto の
put_metric_data で値を投入する。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from dr_switch.core import ContinuableError, NotRecoverableError, RetryableError
from dr_switch.s3 import handlers as s3h
from tests.conftest import ACCOUNT_ID, REGION, Context

SRC = "dr-test-source"
DST = "dr-test-destination"
ROLE = f"arn:aws:iam::{ACCOUNT_ID}:role/s3-replication"


def _put_replication(client, bucket: str, *rules: tuple[str, str]) -> None:
    client.put_bucket_replication(
        Bucket=bucket,
        ReplicationConfiguration={
            "Role": ROLE,
            "Rules": [
                {
                    "ID": rule_id,
                    "Status": status,
                    "Priority": i,
                    "Filter": {},
                    "DeleteMarkerReplication": {"Status": "Disabled"},
                    "Destination": {
                        "Bucket": f"arn:aws:s3:::{DST}",
                        "Metrics": {"Status": "Enabled"},
                    },
                }
                for i, (rule_id, status) in enumerate(rules)
            ],
        },
    )


def _statuses(client, bucket: str) -> dict[str, str]:
    rules = client.get_bucket_replication(
        Bucket=bucket)["ReplicationConfiguration"]["Rules"]
    return {r["ID"]: r["Status"] for r in rules}


@pytest.fixture
def s3(env):
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        for bucket in (SRC, DST):
            client.create_bucket(
                Bucket=bucket,
                CreateBucketConfiguration={"LocationConstraint": REGION})
            client.put_bucket_versioning(
                Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
        env(REPLICATION_BUCKETS=json.dumps([SRC]), REPLICATION_LOOKBACK="300")
        yield client


def _put_pending_metric(value: float, rule_id: str = "r1",
                        bucket: str = SRC) -> None:
    """OperationsPendingReplication に値を投入する.

    実環境では S3 が発行するもので、AWS/ 名前空間へは PutMetricData できない。
    moto のバックエンド内では書けるため、テストではこれを使う。
    """
    cw = boto3.client("cloudwatch", region_name=REGION)
    cw.put_metric_data(
        Namespace="AWS/S3",
        MetricData=[{
            "MetricName": "OperationsPendingReplication",
            "Dimensions": [
                {"Name": "DestinationBucket", "Value": bucket},
                {"Name": "RuleId", "Value": rule_id},
            ],
            "Value": value,
            "Timestamp": datetime.now(UTC) - timedelta(seconds=30),
        }],
    )


# --- block -----------------------------------------------------------------


def test_block_disables_all_rules(s3):
    _put_replication(s3, SRC, ("r1", "Enabled"), ("r2", "Enabled"))
    assert s3h.block({}, Context()) is None
    assert _statuses(s3, SRC) == {"r1": "Disabled", "r2": "Disabled"}


def test_block_is_idempotent(s3):
    _put_replication(s3, SRC, ("r1", "Disabled"))
    s3h.block({}, Context())
    assert _statuses(s3, SRC) == {"r1": "Disabled"}


def test_block_dry_run_does_not_change(s3):
    _put_replication(s3, SRC, ("r1", "Enabled"))
    s3h.block({"dry_run": True}, Context())
    assert _statuses(s3, SRC) == {"r1": "Enabled"}


# --- enable ----------------------------------------------------------------


def test_enable_enables_all_rules(s3):
    _put_replication(s3, SRC, ("r1", "Disabled"), ("r2", "Disabled"))
    assert s3h.enable({}, Context()) is None
    assert _statuses(s3, SRC) == {"r1": "Enabled", "r2": "Enabled"}


def test_enable_preserves_destination(s3):
    """put_bucket_replication は全置換なので、宛先が消えないこと."""
    _put_replication(s3, SRC, ("r1", "Disabled"))
    s3h.enable({}, Context())
    rules = s3.get_bucket_replication(
        Bucket=SRC)["ReplicationConfiguration"]["Rules"]
    assert rules[0]["Destination"]["Bucket"] == f"arn:aws:s3:::{DST}"


def test_enable_dry_run_does_not_change(s3):
    _put_replication(s3, SRC, ("r1", "Disabled"))
    s3h.enable({"dry_run": True}, Context())
    assert _statuses(s3, SRC) == {"r1": "Disabled"}


# --- check -----------------------------------------------------------------


def test_check_passes_when_enabled_and_no_backlog(s3):
    _put_replication(s3, SRC, ("r1", "Enabled"))
    _put_pending_metric(0.0)
    assert s3h.check({}, Context()) is None


def test_check_detects_disabled_rule(s3):
    _put_replication(s3, SRC, ("r1", "Disabled"))
    with pytest.raises(RetryableError) as excinfo:
        s3h.check({}, Context())
    detail = json.loads(str(excinfo.value))["s3-check"][SRC]
    assert detail["rules_not_enabled"] == {"r1": "Disabled"}


def test_check_detects_pending_replication(s3):
    _put_replication(s3, SRC, ("r1", "Enabled"))
    _put_pending_metric(42.0)
    with pytest.raises(RetryableError) as excinfo:
        s3h.check({}, Context())
    detail = json.loads(str(excinfo.value))["s3-check"][SRC]
    assert detail["operations_pending_replication"] == {"r1": 42.0}


def test_check_skips_when_metric_absent(s3):
    """メトリクスはベストエフォート配信。データが無い場合は判定しない."""
    _put_replication(s3, SRC, ("r1", "Enabled"))
    assert s3h.check({}, Context()) is None


def test_check_stops_when_replication_not_configured(s3):
    """設定そのものが無い状態は待っても現れない."""
    with pytest.raises(NotRecoverableError) as excinfo:
        s3h.check({}, Context())
    detail = json.loads(str(excinfo.value))["s3"][SRC]
    assert "does not exist" in detail["reason"]


def test_check_uses_latest_datapoint(s3):
    """複数のデータポイントがあれば最新を見る."""
    _put_replication(s3, SRC, ("r1", "Enabled"))
    cw = boto3.client("cloudwatch", region_name=REGION)
    now = datetime.now(UTC)
    cw.put_metric_data(Namespace="AWS/S3", MetricData=[
        {"MetricName": "OperationsPendingReplication",
         "Dimensions": [{"Name": "DestinationBucket", "Value": SRC},
                        {"Name": "RuleId", "Value": "r1"}],
         "Value": v, "Timestamp": now - timedelta(seconds=age)}
        for v, age in ((99.0, 240), (0.0, 30))
    ])
    assert s3h.check({}, Context()) is None


# --- 例外の分類 -------------------------------------------------------------


def test_check_reraises_unexpected_client_error(s3, monkeypatch):
    """ReplicationConfigurationNotFoundError 以外はそのまま送出する."""

    def denied(**_kwargs):
        raise ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}},
            "GetBucketReplication")

    monkeypatch.setattr(s3, "get_bucket_replication", denied)
    monkeypatch.setattr(s3h, "client",
                        lambda svc, *_a, **_k: s3 if svc == "s3"
                        else boto3.client(svc, region_name=REGION))
    with pytest.raises(ClientError):
        s3h.check({}, Context())


def test_block_continues_on_permanent_error(s3, monkeypatch):
    _put_replication(s3, SRC, ("r1", "Enabled"))

    def deny(**_kwargs):
        raise ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}},
            "PutBucketReplication")

    monkeypatch.setattr(s3, "put_bucket_replication", deny)
    monkeypatch.setattr(s3h, "client", lambda *_a, **_k: s3)
    with pytest.raises(ContinuableError):
        s3h.block({}, Context())
