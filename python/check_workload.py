"""dr-check-workload: EKS のワークロードとノードを確認する.

kubeconfig は AWS CLI の update-kubeconfig で生成する。CA 証明書と
トークン取得は CLI が担うため Python 側の実装は不要。

必要な IAM:
    eks:DescribeCluster / sts:GetCallerIdentity
    ワークロードの参照権限は IAM ではなく Kubernetes RBAC 側

入力 : {}   出力 : 正常時は無し / 未収束なら RetryableError
"""

from __future__ import annotations

import os
import subprocess

from kubernetes import client as k8s
from kubernetes import config as k8s_config

from config import ClusterConfig, EksConfig
from handlers import check_handler
from logging_json import get_logger

logger = get_logger(__name__)

KUBECONFIG_DIR = "/tmp"  # noqa: S108 - Lambda で書けるのは /tmp のみ
AWS_CLI = os.environ.get("AWS_CLI_PATH", "aws")
UPDATE_KUBECONFIG_TIMEOUT_SEC = 15
# Kubernetes API 呼び出しのタイムアウト (connect, read)
K8S_TIMEOUT = (3, 10)


class ClusterApis:
    """1 クラスタ分の API クライアント。"""

    def __init__(self, apps: k8s.AppsV1Api, core: k8s.CoreV1Api) -> None:
        self.apps = apps
        self.core = core


def _build_apis(cfg: EksConfig, cluster: ClusterConfig) -> ClusterApis:
    # Lambda で書けるのは /tmp のみ。ベースイメージ側の値を無条件に上書きする。
    os.environ["HOME"] = KUBECONFIG_DIR
    path = f"{KUBECONFIG_DIR}/kubeconfig-{cluster.name}"

    # 毎回生成する（再利用すると不完全なファイルが残ったまま固定される）。
    subprocess.run(  # noqa: S603
        [AWS_CLI, "eks", "update-kubeconfig",
         "--name", cluster.name,
         "--region", cfg.region,
         "--kubeconfig", path],
        check=True, capture_output=True,
        timeout=UPDATE_KUBECONFIG_TIMEOUT_SEC,
    )
    k8s_config.load_kube_config(config_file=path)
    return ClusterApis(k8s.AppsV1Api(), k8s.CoreV1Api())


def _deployment_problems(apis: ClusterApis, namespaces: list[str]) -> dict:
    """spec.replicas に収束していない Deployment を返す.

    kubectl get deployments -n <ns> の READY 列（<ready>/<want>）に相当。
    status.replicas（作成済み数）ではなく ready_replicas で判定する。
    """
    problems = {}
    for ns in namespaces:
        for dep in apis.apps.list_namespaced_deployment(
                ns, _request_timeout=K8S_TIMEOUT).items:
            want = dep.spec.replicas or 0
            ready = dep.status.ready_replicas or 0
            if ready < want:
                problems[f"{ns}/{dep.metadata.name}"] = {
                    "ready": ready, "want": want}
    return problems


def _daemonset_problems(apis: ClusterApis, namespaces: list[str]) -> dict:
    """desiredNumberScheduled に達していない DaemonSet を返す.

    kubectl get daemonsets -n <ns> の DESIRED 列 / READY 列に相当。
    misscheduled は既定の列に出ないため kubectl describe daemonset の
    Misscheduled に相当する。

    desiredNumberScheduled は Pod 数ではなくノード数由来のため、対象ノードが
    消えると 0 になり numberReady と一致してしまう。0 は異常として扱う。
    """
    problems = {}
    for ns in namespaces:
        for ds in apis.apps.list_namespaced_daemon_set(
                ns, _request_timeout=K8S_TIMEOUT).items:
            status = ds.status
            desired = status.desired_number_scheduled or 0
            ready = status.number_ready or 0
            misscheduled = status.number_misscheduled or 0
            if desired == 0:
                problems[f"{ns}/{ds.metadata.name}"] = {
                    "reason": "no node matched the daemonset selector"}
            elif ready < desired or misscheduled > 0:
                problems[f"{ns}/{ds.metadata.name}"] = {
                    "ready": ready, "desired": desired,
                    "misscheduled": misscheduled}
    return problems


def _pending_pods(apis: ClusterApis, namespaces: list[str]) -> list[str]:
    """Pending 状態の Pod を返す（Job 由来のものは除く）.

    kubectl get pods -n <ns> --field-selector status.phase=Pending に相当。
    CronJob が作る Job Pod は起動直後に Pending になるのが正常なため除く。
    """
    pending = []
    for ns in namespaces:
        for pod in apis.core.list_namespaced_pod(
                ns, _request_timeout=K8S_TIMEOUT).items:
            if pod.status.phase != "Pending":
                continue
            owners = pod.metadata.owner_references or []
            if any(o.kind == "Job" for o in owners):
                continue
            pending.append(f"{ns}/{pod.metadata.name}")
    return pending


@check_handler("workload", EksConfig)
def handler(cfg: EksConfig) -> dict:
    problems: dict[str, dict] = {}

    for cluster in cfg.clusters:
        found: dict[str, object] = {}
        apis = _build_apis(cfg, cluster)

        if deployments := _deployment_problems(apis, cluster.namespaces):
            found["deployments"] = deployments
        if daemonsets := _daemonset_problems(apis, cluster.namespaces):
            found["daemonsets"] = daemonsets
        if pending := _pending_pods(apis, cluster.namespaces):
            found["pending_pods"] = pending

        if found:
            problems[cluster.name] = found

    return problems
