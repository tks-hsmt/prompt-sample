"""route53 ハンドラのテスト.

moto は Route 53 のプライベートホストゾーンと Alias レコードを再現するため、
UPSERT の結果が list_resource_record_sets で読み戻せるかまで検証できる。
"""

from __future__ import annotations

import json

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from dr_switch.core import NotRecoverableError, RetryableError
from dr_switch.route53 import handlers as r53h
from tests.conftest import REGION, Context

ZONE_NAME = "nextops3-dev.internal."
RECORD = "gems-ip.nextops3-dev.internal"
_VPCE_SUFFIX = "execute-api.{region}.vpce.amazonaws.com"
TOKYO_VPCE = (
    "vpce-088173abb8f0bf82b-yu86bbn8."
    + _VPCE_SUFFIX.format(region="ap-northeast-1"))
OSAKA_VPCE = (
    "vpce-0aaaaaaaaaaaaaaaa-bbbbbbbb."
    + _VPCE_SUFFIX.format(region="ap-northeast-3"))
TOKYO_ZONE_ID = "Z2E726K9Y6RL4W"
OSAKA_ZONE_ID = "Z2YQB5RD63NC85"


def _upsert(client, zone_id: str, dns_name: str, alias_zone: str) -> None:
    client.change_resource_record_sets(
        HostedZoneId=zone_id,
        ChangeBatch={"Changes": [{
            "Action": "UPSERT",
            "ResourceRecordSet": {
                "Name": f"{RECORD}.",
                "Type": "A",
                "AliasTarget": {
                    "HostedZoneId": alias_zone,
                    "DNSName": dns_name,
                    "EvaluateTargetHealth": True,
                },
            },
        }]})


def _alias(client, zone_id: str) -> str | None:
    for record in client.list_resource_record_sets(
            HostedZoneId=zone_id)["ResourceRecordSets"]:
        if record["Name"] == f"{RECORD}." and record["Type"] == "A":
            return record["AliasTarget"]["DNSName"]
    return None


@pytest.fixture
def route53(env):
    """東京を向いた Alias レコードを 1 つ持つプライベートホストゾーン."""
    with mock_aws():
        ec2 = boto3.client("ec2", region_name=REGION)
        vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
        client = boto3.client("route53", region_name="us-east-1")
        zone_id = client.create_hosted_zone(
            Name=ZONE_NAME, CallerReference="dr-test",
            HostedZoneConfig={"PrivateZone": True},
            VPC={"VPCRegion": REGION, "VPCId": vpc},
        )["HostedZone"]["Id"].split("/")[-1]
        _upsert(client, zone_id, TOKYO_VPCE, TOKYO_ZONE_ID)
        env(HOSTED_ZONE_ID=zone_id, RECORD_NAME=RECORD,
            ALIAS_DNS_NAME=OSAKA_VPCE, ALIAS_HOSTED_ZONE_ID=OSAKA_ZONE_ID)
        yield zone_id, client


# --- switch ----------------------------------------------------------------


def test_switch_points_record_to_target(route53):
    zone_id, client = route53
    assert r53h.switch({}, Context()) is None
    assert _alias(client, zone_id) == OSAKA_VPCE


def test_switch_is_idempotent(route53):
    """既に切替先を向いていれば変更しない."""
    zone_id, client = route53
    r53h.switch({}, Context())
    r53h.switch({}, Context())
    assert _alias(client, zone_id) == OSAKA_VPCE


def test_switch_ignores_trailing_dot(route53, env):
    """レコード名の末尾ドットの有無を問わない."""
    zone_id, client = route53
    env(HOSTED_ZONE_ID=zone_id, RECORD_NAME=f"{RECORD}.",
        ALIAS_DNS_NAME=OSAKA_VPCE, ALIAS_HOSTED_ZONE_ID=OSAKA_ZONE_ID)
    r53h.switch({}, Context())
    assert _alias(client, zone_id) == OSAKA_VPCE


def test_switch_dry_run_does_not_change(route53):
    zone_id, client = route53
    r53h.switch({"dry_run": True}, Context())
    assert _alias(client, zone_id) == TOKYO_VPCE


def test_switch_creates_record_when_absent(route53, env):
    """UPSERT なのでレコードが無ければ作られる."""
    zone_id, client = route53
    client.change_resource_record_sets(
        HostedZoneId=zone_id,
        ChangeBatch={"Changes": [{
            "Action": "DELETE",
            "ResourceRecordSet": {
                "Name": f"{RECORD}.", "Type": "A",
                "AliasTarget": {"HostedZoneId": TOKYO_ZONE_ID,
                                "DNSName": TOKYO_VPCE,
                                "EvaluateTargetHealth": True}}}]})
    r53h.switch({}, Context())
    assert _alias(client, zone_id) == OSAKA_VPCE


def test_switch_sets_target_hosted_zone_id(route53):
    """切替先のホストゾーン ID もリージョン固有なので合わせて変える."""
    zone_id, client = route53
    r53h.switch({}, Context())
    for record in client.list_resource_record_sets(
            HostedZoneId=zone_id)["ResourceRecordSets"]:
        if record["Name"] == f"{RECORD}." and record["Type"] == "A":
            assert record["AliasTarget"]["HostedZoneId"] == OSAKA_ZONE_ID


# --- check -----------------------------------------------------------------


def test_check_passes_after_switch(route53):
    r53h.switch({}, Context())
    assert r53h.check({}, Context()) is None


def test_check_detects_old_target(route53):
    with pytest.raises(RetryableError) as excinfo:
        r53h.check({}, Context())
    detail = json.loads(str(excinfo.value))["route53-check"]
    assert detail["alias_dns_name"] == TOKYO_VPCE
    assert detail["expected"] == OSAKA_VPCE


def test_check_stops_when_record_missing(route53, env):
    zone_id, _ = route53
    env(HOSTED_ZONE_ID=zone_id, RECORD_NAME="absent.nextops3-dev.internal",
        ALIAS_DNS_NAME=OSAKA_VPCE, ALIAS_HOSTED_ZONE_ID=OSAKA_ZONE_ID)
    with pytest.raises(NotRecoverableError) as excinfo:
        r53h.check({}, Context())
    detail = json.loads(str(excinfo.value))["route53"]
    assert "does not exist" in detail["absent.nextops3-dev.internal."]["reason"]


def test_check_ignores_case_and_trailing_dot(route53, env):
    """Route 53 の応答は末尾ドット付き。設定値との比較で差が出ないこと."""
    zone_id, _ = route53
    env(HOSTED_ZONE_ID=zone_id, RECORD_NAME=RECORD,
        ALIAS_DNS_NAME=f"{OSAKA_VPCE.upper()}.",
        ALIAS_HOSTED_ZONE_ID=OSAKA_ZONE_ID)
    r53h.switch({}, Context())
    assert r53h.check({}, Context()) is None


# --- 例外の分類 -------------------------------------------------------------


def test_switch_stops_on_permanent_error(route53, monkeypatch):
    """switch は best_effort=False。恒久エラーはそのまま送出される."""
    _, client = route53

    def deny(**_kwargs):
        raise ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}},
            "ChangeResourceRecordSets")

    monkeypatch.setattr(client, "change_resource_record_sets", deny)
    monkeypatch.setattr(r53h, "client", lambda *_a, **_k: client)
    with pytest.raises(ClientError):
        r53h.switch({}, Context())


def test_switch_retries_on_prior_request_not_complete(route53, monkeypatch):
    """PriorRequestNotComplete は botocore が再試行対象としている."""
    _, client = route53

    def busy(**_kwargs):
        raise ClientError(
            {"Error": {"Code": "PriorRequestNotComplete", "Message": "busy"}},
            "ChangeResourceRecordSets")

    monkeypatch.setattr(client, "change_resource_record_sets", busy)
    monkeypatch.setattr(r53h, "client", lambda *_a, **_k: client)
    with pytest.raises(RetryableError):
        r53h.switch({}, Context())
