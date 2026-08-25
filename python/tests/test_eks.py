"""eks ハンドラのテスト.

Kubernetes API は moto の対象外。Python の kubernetes クライアントには
Go の client-go にある fake クライアント相当が存在しない（要望の Issue は
2018 年から未実装）。そのため AppsV1Api / CoreV1Api を差し替える。

素の dict や自作クラスではなく **kubernetes.client.models の本物のモデル**
を使って応答を組み立てる。属性名の誤りや存在しないフィールドが検出できる。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import zipfile
from subprocess import CompletedProcess

import boto3
import pytest
from kubernetes import config as k8s_config
from kubernetes.client.models import (
    V1DaemonSet,
    V1DaemonSetList,
    V1DaemonSetStatus,
    V1Deployment,
    V1DeploymentList,
    V1DeploymentSpec,
    V1DeploymentStatus,
    V1LabelSelector,
    V1ObjectMeta,
    V1OwnerReference,
    V1Pod,
    V1PodList,
    V1PodStatus,
    V1PodTemplateSpec,
)
from moto import mock_aws

from dr_switch.core import NotRecoverableError, RetryableError
from dr_switch.eks import handlers as eksh
from dr_switch.eks.config import EksCheckConfig
from tests.conftest import ACCOUNT_ID, REGION, Context

CLUSTER = "dr-test-cluster"
NAMESPACE = "gems-ip"

EKS_CLUSTERS = json.dumps([{
    "name": CLUSTER,
    "namespaces": [{
        "name": NAMESPACE,
        "restart_targets": [
            {"kind": "Deployment", "name": "app-a"},
            {"kind": "DaemonSet", "name": "ds-a"},
        ],
    }],
}])


# --- Kubernetes オブジェクトの組み立て --------------------------------------


def _deployment(name: str, want: int, ready: int | None) -> V1Deployment:
    return V1Deployment(
        metadata=V1ObjectMeta(name=name, namespace=NAMESPACE),
        spec=V1DeploymentSpec(
            replicas=want,
            selector=V1LabelSelector(match_labels={"app": name}),
            template=V1PodTemplateSpec(metadata=V1ObjectMeta(labels={"app": name})),
        ),
        status=V1DeploymentStatus(ready_replicas=ready),
    )


def _daemonset(name: str, desired: int, ready: int,
               misscheduled: int = 0) -> V1DaemonSet:
    return V1DaemonSet(
        metadata=V1ObjectMeta(name=name, namespace=NAMESPACE),
        status=V1DaemonSetStatus(
            current_number_scheduled=desired,
            desired_number_scheduled=desired,
            number_misscheduled=misscheduled,
            number_ready=ready,
        ),
    )


def _pod(name: str, phase: str, owner_kind: str | None = None) -> V1Pod:
    owners = ([V1OwnerReference(api_version="batch/v1", kind=owner_kind,
                                name="job-1", uid="u1")]
              if owner_kind else None)
    return V1Pod(
        metadata=V1ObjectMeta(name=name, namespace=NAMESPACE,
                              owner_references=owners),
        status=V1PodStatus(phase=phase),
    )


class FakeAppsV1Api:
    """AppsV1Api の差し替え。patch の呼び出しを記録する."""

    def __init__(self, deployments=None, daemonsets=None):
        self._deployments = deployments or []
        self._daemonsets = daemonsets or []
        self.patched: list[tuple[str, str, dict]] = []

    def list_namespaced_deployment(self, namespace, **_kwargs):
        return V1DeploymentList(items=self._deployments)

    def list_namespaced_daemon_set(self, namespace, **_kwargs):
        return V1DaemonSetList(items=self._daemonsets)

    def patch_namespaced_deployment(self, name, namespace, body, **_kwargs):
        self.patched.append(("Deployment", name, body))

    def patch_namespaced_daemon_set(self, name, namespace, body, **_kwargs):
        self.patched.append(("DaemonSet", name, body))


class FakeCoreV1Api:
    def __init__(self, pods=None):
        self._pods = pods or []

    def list_namespaced_pod(self, namespace, **_kwargs):
        return V1PodList(items=self._pods)


@pytest.fixture
def k8s(env, monkeypatch):
    """kubeconfig の生成を潰し、API クライアントを差し替える helper を返す."""
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **_k: CompletedProcess(a, 0, b"", b""))
    monkeypatch.setattr(k8s_config, "load_kube_config", lambda **_k: None)
    env(EKS_CLUSTERS=EKS_CLUSTERS,
        POD_RESTART_FUNCTIONS=json.dumps([]), POD_RESTART_TIMEOUT="300")

    def _install(*, deployments=None, daemonsets=None, pods=None):
        apis = eksh.ClusterApis(
            FakeAppsV1Api(deployments, daemonsets), FakeCoreV1Api(pods))
        monkeypatch.setattr(eksh, "_build_apis", lambda _cfg, _cluster: apis)
        return apis

    return _install


# --- _build_apis -----------------------------------------------------------


def test_build_apis_generates_kubeconfig(env, monkeypatch, tmp_path):
    """update-kubeconfig を毎回実行し、HOME を /tmp に上書きする.

    Lambda で書けるのは /tmp のみ。ベースイメージ側の HOME が別の場所を
    指していると kubeconfig を書けない。
    """
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        assert kwargs["check"] is True
        assert kwargs["timeout"] == eksh.UPDATE_KUBECONFIG_TIMEOUT_SEC
        return CompletedProcess(cmd, 0, b"", b"")

    loaded: dict = {}
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(k8s_config, "load_kube_config",
                        lambda **kw: loaded.update(kw))
    monkeypatch.setenv("HOME", str(tmp_path))
    env(EKS_CLUSTERS=EKS_CLUSTERS)

    cfg = EksCheckConfig.from_env()
    cluster = cfg.clusters[0]
    apis = eksh._build_apis(cfg, cluster)

    assert calls[0][:4] == [eksh.AWS_CLI, "eks", "update-kubeconfig", "--name"]
    assert cluster.name in calls[0]
    assert REGION in calls[0]
    assert loaded["config_file"].startswith(eksh.KUBECONFIG_DIR)
    assert os.environ["HOME"] == eksh.KUBECONFIG_DIR
    assert isinstance(apis, eksh.ClusterApis)


# --- check -----------------------------------------------------------------


def test_check_passes_when_converged(k8s):
    k8s(deployments=[_deployment("app-a", 3, 3)],
        daemonsets=[_daemonset("ds-a", 2, 2)])
    assert eksh.check({}, Context()) is None


def test_check_detects_deployment_not_ready(k8s):
    """status.replicas ではなく spec.replicas を分母にする."""
    k8s(deployments=[_deployment("app-a", 3, 1)])
    with pytest.raises(RetryableError) as excinfo:
        eksh.check({}, Context())
    detail = json.loads(str(excinfo.value))["eks-check"][CLUSTER]["deployments"]
    assert detail[f"{NAMESPACE}/app-a"] == {"ready": 1, "want": 3}


def test_check_treats_none_ready_replicas_as_zero(k8s):
    """readyReplicas は Pod が 1 つも Ready でないと省略される."""
    k8s(deployments=[_deployment("app-a", 2, None)])
    with pytest.raises(RetryableError) as excinfo:
        eksh.check({}, Context())
    detail = json.loads(str(excinfo.value))["eks-check"][CLUSTER]["deployments"]
    assert detail[f"{NAMESPACE}/app-a"]["ready"] == 0


def test_check_detects_daemonset_not_ready(k8s):
    k8s(daemonsets=[_daemonset("ds-a", 3, 1)])
    with pytest.raises(RetryableError) as excinfo:
        eksh.check({}, Context())
    detail = json.loads(str(excinfo.value))["eks-check"][CLUSTER]["daemonsets"]
    assert detail[f"{NAMESPACE}/ds-a"]["ready"] == 1


def test_check_detects_misscheduled_daemonset(k8s):
    k8s(daemonsets=[_daemonset("ds-a", 2, 2, misscheduled=1)])
    with pytest.raises(RetryableError) as excinfo:
        eksh.check({}, Context())
    detail = json.loads(str(excinfo.value))["eks-check"][CLUSTER]["daemonsets"]
    assert detail[f"{NAMESPACE}/ds-a"]["misscheduled"] == 1


def test_check_stops_when_daemonset_has_no_node(k8s):
    """desiredNumberScheduled == 0 はノードが消えた状態。待っても戻らない."""
    k8s(daemonsets=[_daemonset("ds-a", 0, 0)])
    with pytest.raises(NotRecoverableError) as excinfo:
        eksh.check({}, Context())
    detail = json.loads(str(excinfo.value))["workload"][CLUSTER]["daemonsets"]
    assert "no node matched" in detail[f"{NAMESPACE}/ds-a"]["reason"]


def test_check_detects_pending_pod(k8s):
    k8s(pods=[_pod("p1", "Pending")])
    with pytest.raises(RetryableError) as excinfo:
        eksh.check({}, Context())
    detail = json.loads(str(excinfo.value))["eks-check"][CLUSTER]["pending_pods"]
    assert detail == [f"{NAMESPACE}/p1"]


def test_check_ignores_job_pods(k8s):
    """CronJob が作る Job Pod は起動直後に Pending になるのが正常."""
    k8s(pods=[_pod("p1", "Pending", owner_kind="Job")])
    assert eksh.check({}, Context()) is None


def test_check_ignores_running_pods(k8s):
    """CrashLoopBackOff は phase が Running。Ready 数の判定で拾う."""
    k8s(pods=[_pod("p1", "Running")])
    assert eksh.check({}, Context()) is None


# --- rollout_restart -------------------------------------------------------


def test_rollout_restart_patches_configured_targets(k8s):
    apis = k8s()
    assert eksh.rollout_restart({}, Context()) is None
    kinds = [(kind, name) for kind, name, _ in apis.apps.patched]
    assert kinds == [("Deployment", "app-a"), ("DaemonSet", "ds-a")]


def test_rollout_restart_sets_restarted_at_annotation(k8s):
    """kubectl rollout restart と同じアノテーションを書く."""
    apis = k8s()
    eksh.rollout_restart({}, Context())
    _, _, body = apis.apps.patched[0]
    annotations = body["spec"]["template"]["metadata"]["annotations"]
    assert "kubectl.kubernetes.io/restartedAt" in annotations


def test_rollout_restart_dry_run_does_not_patch(k8s):
    apis = k8s()
    eksh.rollout_restart({"dry_run": True}, Context())
    assert apis.apps.patched == []


def test_rollout_restart_skips_cluster_without_targets(env, monkeypatch):
    """対象が 1 つも無いクラスタは kubeconfig の生成もしない."""
    built: list[str] = []
    monkeypatch.setattr(eksh, "_build_apis",
                        lambda _c, cluster: built.append(cluster.name))
    env(EKS_CLUSTERS=json.dumps([{
        "name": CLUSTER,
        "namespaces": [{"name": NAMESPACE, "restart_targets": []}],
    }]))
    assert eksh.rollout_restart({}, Context()) is None
    assert built == []


def test_rollout_restart_rejects_unsupported_kind(env, monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **_k: CompletedProcess(a, 0, b"", b""))
    monkeypatch.setattr(k8s_config, "load_kube_config", lambda **_k: None)
    monkeypatch.setattr(
        eksh, "_build_apis",
        lambda _c, _cl: eksh.ClusterApis(FakeAppsV1Api(), FakeCoreV1Api()))
    env(EKS_CLUSTERS=json.dumps([{
        "name": CLUSTER,
        "namespaces": [{"name": NAMESPACE, "restart_targets": [
            {"kind": "StatefulSet", "name": "sts-a"}]}],
    }]))
    with pytest.raises(NotRecoverableError) as excinfo:
        eksh.rollout_restart({}, Context())
    assert "unsupported restart kind" in str(excinfo.value)


# --- restart_pods ----------------------------------------------------------


def _create_lambda(name: str) -> str:
    iam = boto3.client("iam", region_name=REGION)
    with contextlib.suppress(iam.exceptions.EntityAlreadyExistsException):
        iam.create_role(RoleName="lambda-exec",
                        AssumeRolePolicyDocument=json.dumps({"Version": "2012-10-17"}))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("index.py", "def handler(event, context): return {}")
    boto3.client("lambda", region_name=REGION).create_function(
        FunctionName=name, Runtime="python3.13",
        Role=f"arn:aws:iam::{ACCOUNT_ID}:role/lambda-exec",
        Handler="index.handler", Code={"ZipFile": buf.getvalue()})
    return name


@pytest.fixture
def pod_restart(env):
    with mock_aws():
        for name in ("restart-1", "restart-2"):
            _create_lambda(name)
        env(POD_RESTART_FUNCTIONS=json.dumps(["restart-1", "restart-2"]),
            POD_RESTART_TIMEOUT="300")
        yield


def test_restart_pods_invokes_all(pod_restart, monkeypatch):
    called: list[str] = []
    client = boto3.client("lambda", region_name=REGION)
    monkeypatch.setattr(client, "invoke", lambda **kw: (
        called.append(kw["FunctionName"]), {"StatusCode": 200})[1])
    monkeypatch.setattr(eksh, "client", lambda *_a, **_k: client)
    assert eksh.restart_pods({}, Context()) is None
    assert sorted(called) == ["restart-1", "restart-2"]


def test_restart_pods_dry_run_does_not_invoke(pod_restart, monkeypatch):
    called: list[str] = []
    client = boto3.client("lambda", region_name=REGION)
    monkeypatch.setattr(client, "invoke", lambda **kw: (
        called.append(kw["FunctionName"]), {"StatusCode": 200})[1])
    monkeypatch.setattr(eksh, "client", lambda *_a, **_k: client)
    eksh.restart_pods({"dry_run": True}, Context())
    assert called == []


def test_restart_pods_reports_all_failures(pod_restart, monkeypatch):
    """全件投げてから集約する。途中で中断できないため."""
    client = boto3.client("lambda", region_name=REGION)

    def failing(**kw):
        return {"StatusCode": 200, "FunctionError": "Unhandled",
                "Payload": io.BytesIO(b'{"errorMessage": "boom"}')}

    monkeypatch.setattr(client, "invoke", failing)
    monkeypatch.setattr(eksh, "client", lambda *_a, **_k: client)
    with pytest.raises(NotRecoverableError) as excinfo:
        eksh.restart_pods({}, Context())
    failures = json.loads(str(excinfo.value))["pod_restart"]
    assert sorted(failures) == ["restart-1", "restart-2"]


def test_restart_pods_with_empty_list(env):
    env(POD_RESTART_FUNCTIONS=json.dumps([]), POD_RESTART_TIMEOUT="300")
    assert eksh.restart_pods({}, Context()) is None


def test_restart_pods_uses_configured_timeout(pod_restart, monkeypatch, env):
    """POD_RESTART_TIMEOUT が read_timeout に反映される."""
    env(POD_RESTART_FUNCTIONS=json.dumps(["restart-1"]),
        POD_RESTART_TIMEOUT="600")
    captured: dict = {}

    def capture(service, region, config):
        captured["read_timeout"] = config.read_timeout
        client = boto3.client(service, region_name=region)
        monkeypatch.setattr(client, "invoke", lambda **_k: {"StatusCode": 200})
        return client

    monkeypatch.setattr(eksh, "client", capture)
    eksh.restart_pods({}, Context())
    assert captured["read_timeout"] == 600
