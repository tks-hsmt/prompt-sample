"""単純な観測系ハンドラのテスト（lambda / dynamodb / nlb / cloudwatch / efs）.

いずれも読み取り専用で、moto が返す状態をそのまま判定する。
moto が再現しない状態（Lambda の Inactive など）は応答を差し替えて検証する。
"""

from __future__ import annotations

import contextlib
import io
import json
import zipfile

import boto3
import pytest
from moto import mock_aws

from dr_switch.cloudwatch import handlers as cwh
from dr_switch.core import NotRecoverableError, RetryableError
from dr_switch.dynamodb import handlers as ddbh
from dr_switch.efs import handlers as efsh
from dr_switch.lambda_function import handlers as lamh
from dr_switch.nlb import handlers as nlbh
from tests.conftest import ACCOUNT_ID, REGION, Context

ROLE = f"arn:aws:iam::{ACCOUNT_ID}:role/lambda-exec"


# ===========================================================================
# lambda-check
# ===========================================================================


def _create_lambda(name: str) -> None:
    iam = boto3.client("iam", region_name=REGION)
    with contextlib.suppress(iam.exceptions.EntityAlreadyExistsException):
        iam.create_role(RoleName="lambda-exec",
                        AssumeRolePolicyDocument=json.dumps({"Version": "2012-10-17"}))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("index.py", "def handler(event, context): pass")
    boto3.client("lambda", region_name=REGION).create_function(
        FunctionName=name, Runtime="python3.13", Role=ROLE,
        Handler="index.handler", Code={"ZipFile": buf.getvalue()})


@pytest.fixture
def lambda_env(env):
    with mock_aws():
        _create_lambda("app-1")
        env(FUNCTION_NAMES=json.dumps(["app-1"]))
        yield


def test_lambda_check_passes_when_active(lambda_env):
    assert lamh.check({}, Context()) is None


@pytest.mark.parametrize("state", ["Pending"])
def test_lambda_check_retries_on_transient_state(lambda_env, monkeypatch, state):
    _stub_function_state(monkeypatch, state=state)
    with pytest.raises(RetryableError) as excinfo:
        lamh.check({}, Context())
    assert json.loads(str(excinfo.value))["lambda-check"]["app-1"]["state"] == state


@pytest.mark.parametrize("state", [
    "Inactive", "Failed", "Deactivating", "Deactivated",
    "ActiveNonInvocable", "Deleting",
])
def test_lambda_check_stops_on_fatal_state(lambda_env, monkeypatch, state):
    """Inactive は呼び出しでしか解消せず、確認フェーズでは誰も呼ばない."""
    _stub_function_state(monkeypatch, state=state)
    with pytest.raises(NotRecoverableError) as excinfo:
        lamh.check({}, Context())
    assert json.loads(str(excinfo.value))["lambda"]["app-1"]["state"] == state


def test_lambda_check_retries_on_update_in_progress(lambda_env, monkeypatch):
    _stub_function_state(monkeypatch, update="InProgress")
    with pytest.raises(RetryableError):
        lamh.check({}, Context())


def test_lambda_check_stops_on_update_failed(lambda_env, monkeypatch):
    _stub_function_state(monkeypatch, update="Failed")
    with pytest.raises(NotRecoverableError):
        lamh.check({}, Context())


def _stub_function_state(monkeypatch, *, state: str = "Active",
                         update: str = "Successful") -> None:
    """moto の get_function_configuration の応答に State を混ぜる.

    moto は常に Active 相当を返すため、異常系はここで作る。
    """
    client = boto3.client("lambda", region_name=REGION)
    original = client.get_function_configuration

    def patched(**kwargs):
        return {**original(**kwargs), "State": state,
                "LastUpdateStatus": update,
                "StateReason": "stubbed", "LastUpdateStatusReason": "stubbed"}

    monkeypatch.setattr(client, "get_function_configuration", patched)
    monkeypatch.setattr(lamh, "client", lambda *_a, **_k: client)


# ===========================================================================
# dynamodb-check
# ===========================================================================


@pytest.fixture
def dynamodb_env(env):
    with mock_aws():
        boto3.client("dynamodb", region_name=REGION).create_table(
            TableName="t1",
            KeySchema=[{"AttributeName": "k", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "k", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST")
        env(TABLE_NAMES=json.dumps(["t1"]))
        yield


def test_dynamodb_check_passes_when_active(dynamodb_env):
    assert ddbh.check({}, Context()) is None


@pytest.mark.parametrize("status", ["CREATING", "UPDATING"])
def test_dynamodb_check_retries_on_transient(dynamodb_env, monkeypatch, status):
    _stub_table_status(monkeypatch, status)
    with pytest.raises(RetryableError) as excinfo:
        ddbh.check({}, Context())
    assert json.loads(str(excinfo.value))["dynamodb-check"]["t1"]["status"] == status


@pytest.mark.parametrize("status", [
    "DELETING", "ARCHIVING", "ARCHIVED",
    "INACCESSIBLE_ENCRYPTION_CREDENTIALS", "REPLICATION_NOT_AUTHORIZED",
])
def test_dynamodb_check_stops_on_fatal(dynamodb_env, monkeypatch, status):
    _stub_table_status(monkeypatch, status)
    with pytest.raises(NotRecoverableError) as excinfo:
        ddbh.check({}, Context())
    assert json.loads(str(excinfo.value))["dynamodb"]["t1"]["status"] == status


def _stub_table_status(monkeypatch, status: str) -> None:
    client = boto3.client("dynamodb", region_name=REGION)
    original = client.describe_table

    def patched(**kwargs):
        result = original(**kwargs)
        result["Table"]["TableStatus"] = status
        return result

    monkeypatch.setattr(client, "describe_table", patched)
    monkeypatch.setattr(ddbh, "client", lambda *_a, **_k: client)


# ===========================================================================
# nlb-check
# ===========================================================================


@pytest.fixture
def nlb_env(env):
    with mock_aws():
        ec2 = boto3.client("ec2", region_name=REGION)
        vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
        elb = boto3.client("elbv2", region_name=REGION)
        tg = elb.create_target_group(
            Name="tg1", Protocol="TCP", Port=80, VpcId=vpc,
            TargetType="ip")["TargetGroups"][0]["TargetGroupArn"]
        env(TARGET_GROUP_ARNS=json.dumps([tg]),
            LOAD_BALANCER_ARNS=json.dumps([]))
        yield tg


def test_nlb_check_detects_no_healthy_target(nlb_env):
    """ターゲットが 1 つも登録されていなければ healthy < 1."""
    with pytest.raises(RetryableError) as excinfo:
        nlbh.check({}, Context())
    detail = json.loads(str(excinfo.value))["nlb-check"][nlb_env]
    assert detail["healthy"] == 0


def test_nlb_check_passes_with_healthy_target(nlb_env, monkeypatch):
    _stub_target_health(monkeypatch, ["healthy", "healthy"])
    assert nlbh.check({}, Context()) is None


@pytest.mark.parametrize("states", [
    ["healthy", "unhealthy"],
    ["healthy", "unused"],
    ["healthy", "unavailable"],
])
def test_nlb_check_detects_unhealthy_states(nlb_env, monkeypatch, states):
    """unused / unavailable も異常として扱う."""
    _stub_target_health(monkeypatch, states)
    with pytest.raises(RetryableError) as excinfo:
        nlbh.check({}, Context())
    assert json.loads(str(excinfo.value))["nlb-check"][nlb_env]["unhealthy"] == 1


@pytest.mark.parametrize("states", [
    ["healthy", "initial"],
    ["healthy", "draining"],
    ["healthy", "unhealthy.draining"],
])
def test_nlb_check_detects_transient_states(nlb_env, monkeypatch, states):
    _stub_target_health(monkeypatch, states)
    with pytest.raises(RetryableError) as excinfo:
        nlbh.check({}, Context())
    assert json.loads(str(excinfo.value))["nlb-check"][nlb_env]["transient"] == 1


def test_nlb_check_passes_with_active_load_balancer(nlb_env, monkeypatch, env):
    _stub_target_health(monkeypatch, ["healthy"])
    _stub_load_balancers(monkeypatch, "active")
    env(TARGET_GROUP_ARNS=json.dumps([nlb_env]),
        LOAD_BALANCER_ARNS=json.dumps(["lb-1"]))
    assert nlbh.check({}, Context()) is None


@pytest.mark.parametrize("code", ["provisioning", "active_impaired"])
def test_nlb_check_retries_on_transient_lb_state(nlb_env, monkeypatch, env, code):
    _stub_target_health(monkeypatch, ["healthy"])
    _stub_load_balancers(monkeypatch, code)
    env(TARGET_GROUP_ARNS=json.dumps([nlb_env]),
        LOAD_BALANCER_ARNS=json.dumps(["lb-1"]))
    with pytest.raises(RetryableError) as excinfo:
        nlbh.check({}, Context())
    assert json.loads(str(excinfo.value))["nlb-check"]["lb-1"]["state"] == code


def test_nlb_check_stops_on_failed_lb_state(nlb_env, monkeypatch, env):
    _stub_target_health(monkeypatch, ["healthy"])
    _stub_load_balancers(monkeypatch, "failed", reason="setup error")
    env(TARGET_GROUP_ARNS=json.dumps([nlb_env]),
        LOAD_BALANCER_ARNS=json.dumps(["lb-1"]))
    with pytest.raises(NotRecoverableError) as excinfo:
        nlbh.check({}, Context())
    detail = json.loads(str(excinfo.value))["nlb"]["lb-1"]
    assert detail == {"state": "failed", "reason": "setup error"}


_elb_client = None


def _elb(monkeypatch):
    global _elb_client  # noqa: PLW0603 - テスト内で 1 つのクライアントを共有する
    if _elb_client is None:
        _elb_client = boto3.client("elbv2", region_name=REGION)
    monkeypatch.setattr(nlbh, "client", lambda *_a, **_k: _elb_client)
    return _elb_client


def _stub_target_health(monkeypatch, states: list[str]) -> None:
    client = _elb(monkeypatch)
    monkeypatch.setattr(client, "describe_target_health", lambda **_k: {
        "TargetHealthDescriptions": [{"TargetHealth": {"State": s}} for s in states]})


def _stub_load_balancers(monkeypatch, code: str, reason: str | None = None) -> None:
    client = _elb(monkeypatch)
    monkeypatch.setattr(client, "describe_load_balancers", lambda **_k: {
        "LoadBalancers": [{"LoadBalancerArn": "lb-1",
                           "State": {"Code": code, "Reason": reason}}]})


# ===========================================================================
# cloudwatch-check
# ===========================================================================


@pytest.fixture
def cloudwatch_env(env, monkeypatch):
    """moto の describe_alarms は AlarmNamePrefix を併用すると StateValue を
    無視する（実測で確認）。実 AWS は両方を適用するため、ここで補正する。

    moto 5.2.3 での挙動。修正されたら不要になる。
    """
    with mock_aws():
        client = boto3.client("cloudwatch", region_name=REGION)
        original = client.describe_alarms

        def both_filters(**kwargs):
            wanted = kwargs.get("StateValue")
            result = original(**kwargs)
            if wanted:
                result["MetricAlarms"] = [
                    a for a in result["MetricAlarms"] if a["StateValue"] == wanted
                ]
            return result

        monkeypatch.setattr(client, "describe_alarms", both_filters)
        monkeypatch.setattr(cwh, "client", lambda *_a, **_k: client)
        env(ALARM_PREFIX="dr-test-")
        yield client


def _put_alarm(client, name: str) -> None:
    client.put_metric_alarm(
        AlarmName=name, MetricName="Errors", Namespace="AWS/Lambda",
        Statistic="Sum", Period=60, EvaluationPeriods=1,
        Threshold=1.0, ComparisonOperator="GreaterThanThreshold")


def test_cloudwatch_check_passes_when_no_alarm(cloudwatch_env):
    _put_alarm(cloudwatch_env, "dr-test-errors")
    assert cwh.check({}, Context()) is None


def test_cloudwatch_check_detects_alarm_state(cloudwatch_env):
    _put_alarm(cloudwatch_env, "dr-test-errors")
    cloudwatch_env.set_alarm_state(
        AlarmName="dr-test-errors", StateValue="ALARM", StateReason="test")
    with pytest.raises(RetryableError) as excinfo:
        cwh.check({}, Context())
    assert json.loads(str(excinfo.value))["cloudwatch-check"]["in_alarm"] == [
        "dr-test-errors"]


def test_cloudwatch_check_without_prefix(cloudwatch_env, env):
    """接頭辞が空なら AlarmNamePrefix を渡さず、全アラームを対象にする."""
    env(ALARM_PREFIX="")
    _put_alarm(cloudwatch_env, "other-team-errors")
    cloudwatch_env.set_alarm_state(
        AlarmName="other-team-errors", StateValue="ALARM", StateReason="test")
    with pytest.raises(RetryableError) as excinfo:
        cwh.check({}, Context())
    assert json.loads(str(excinfo.value))["cloudwatch-check"]["in_alarm"] == [
        "other-team-errors"]


def test_cloudwatch_check_respects_prefix(cloudwatch_env):
    """接頭辞の外のアラームは対象にしない."""
    _put_alarm(cloudwatch_env, "other-team-errors")
    cloudwatch_env.set_alarm_state(
        AlarmName="other-team-errors", StateValue="ALARM", StateReason="test")
    assert cwh.check({}, Context()) is None


# ===========================================================================
# efs-check
# ===========================================================================


@pytest.fixture
def efs_env(env):
    with mock_aws():
        efs = boto3.client("efs", region_name=REGION)
        fs_id = efs.create_file_system(CreationToken="dr-test")["FileSystemId"]
        env(FILE_SYSTEM_IDS=json.dumps([fs_id]))
        yield fs_id, efs


def test_efs_check_passes_when_available(efs_env):
    assert efsh.check({}, Context()) is None


@pytest.mark.parametrize("state", ["creating", "updating"])
def test_efs_check_retries_on_transient(efs_env, monkeypatch, state):
    _stub_efs(monkeypatch, fs_state=state)
    fs_id, _ = efs_env
    with pytest.raises(RetryableError) as excinfo:
        efsh.check({}, Context())
    assert json.loads(str(excinfo.value))["efs-check"][fs_id][
        "life_cycle_state"] == state


@pytest.mark.parametrize("state", ["deleting", "deleted", "error"])
def test_efs_check_stops_on_fatal(efs_env, monkeypatch, state):
    _stub_efs(monkeypatch, fs_state=state)
    fs_id, _ = efs_env
    with pytest.raises(NotRecoverableError) as excinfo:
        efsh.check({}, Context())
    assert json.loads(str(excinfo.value))["efs"][fs_id][
        "life_cycle_state"] == state


def test_efs_check_detects_mount_target_error(efs_env, monkeypatch):
    """ファイルシステムが available でも、マウントターゲットが error なら止める.

    既にマウント済みの Pod は動き続けるため eks の check では拾えない。
    """
    _stub_efs(monkeypatch, mount_targets=[("fsmt-1", "error", "subnet-a")])
    fs_id, _ = efs_env
    with pytest.raises(NotRecoverableError) as excinfo:
        efsh.check({}, Context())
    detail = json.loads(str(excinfo.value))["efs"][f"{fs_id}/fsmt-1"]
    assert detail == {"life_cycle_state": "error", "subnet_id": "subnet-a"}


def test_efs_check_passes_with_available_mount_target(efs_env, monkeypatch):
    """available のマウントターゲットは問題として報告しない."""
    _stub_efs(monkeypatch, mount_targets=[("fsmt-1", "available", "subnet-a")])
    assert efsh.check({}, Context()) is None


def test_efs_check_retries_on_mount_target_creating(efs_env, monkeypatch):
    _stub_efs(monkeypatch, mount_targets=[("fsmt-1", "creating", "subnet-a")])
    fs_id, _ = efs_env
    with pytest.raises(RetryableError) as excinfo:
        efsh.check({}, Context())
    assert json.loads(str(excinfo.value))["efs-check"][f"{fs_id}/fsmt-1"][
        "life_cycle_state"] == "creating"


def _stub_efs(monkeypatch, *, fs_state: str = "available",
              mount_targets: list[tuple[str, str, str]] | None = None) -> None:
    client = boto3.client("efs", region_name=REGION)
    original = client.describe_file_systems

    def fs_patched(**kwargs):
        result = original(**kwargs)
        for fs in result["FileSystems"]:
            fs["LifeCycleState"] = fs_state
        return result

    monkeypatch.setattr(client, "describe_file_systems", fs_patched)
    monkeypatch.setattr(client, "describe_mount_targets", lambda **_k: {
        "MountTargets": [
            {"MountTargetId": mt_id, "LifeCycleState": state, "SubnetId": subnet}
            for mt_id, state, subnet in (mount_targets or [])
        ]})
    monkeypatch.setattr(efsh, "client", lambda *_a, **_k: client)
