"""EKS のワークロードを確認する.

kubeconfig は AWS CLI の update-kubeconfig で生成する。CA 証明書と
トークン取得は CLI が担うため Python 側の実装は不要。

必要な IAM:
    eks:DescribeCluster / sts:GetCallerIdentity
    restart_pods のみ lambda:InvokeFunction
    ワークロードの参照・更新権限は IAM ではなく Kubernetes RBAC 側
    （check は list、rollout_restart は patch が必要）

ハンドラ:
    check            ワークロードが収束しているか確認
    restart_pods     既存の Pod 再起動 Lambda を並列に呼び出す
    rollout_restart  Kubernetes API を直接叩いて rollout restart する

タイムアウト:
    update-kubeconfig は 15 秒、Kubernetes API 呼び出しは (connect 3, read 10) 秒。

ハンドラ（成功時は何も返さない。失敗・未収束は例外で表現する）:
    check   入力 {"dry_run": bool}。成功時は何も返さない。未収束は例外で表現する
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

from botocore.config import Config
from kubernetes import client as k8s
from kubernetes import config as k8s_config

from dr_switch.core import NotRecoverableError, client, lambda_handler
from dr_switch.eks.config import ClusterConfig, EksConfig

logger = logging.getLogger(__name__)

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


def _daemonset_problems(apis: ClusterApis, namespaces: list[str]) -> tuple[dict, dict]:
    """desiredNumberScheduled に達していない DaemonSet を返す.

    kubectl get daemonsets -n <ns> の DESIRED 列 / READY 列に相当。
    misscheduled は既定の列に出ないため kubectl describe daemonset の
    Misscheduled に相当する。

    desiredNumberScheduled は Pod 数ではなくノード数由来のため、対象ノードが
    消えると 0 になり numberReady と一致してしまう。0 は異常として扱う。
    """
    problems: dict = {}
    fatal: dict = {}
    for ns in namespaces:
        for ds in apis.apps.list_namespaced_daemon_set(
                ns, _request_timeout=K8S_TIMEOUT).items:
            status = ds.status
            desired = status.desired_number_scheduled or 0
            ready = status.number_ready or 0
            misscheduled = status.number_misscheduled or 0
            if desired == 0:
                # 対象ノードが 1 台も無い。ノードが戻らない限り解消しない
                fatal[f"{ns}/{ds.metadata.name}"] = {
                    "reason": "no node matched the daemonset selector"}
            elif ready < desired or misscheduled > 0:
                problems[f"{ns}/{ds.metadata.name}"] = {
                    "ready": ready, "desired": desired,
                    "misscheduled": misscheduled}
    return problems, fatal


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


@lambda_handler("eks-check", EksConfig)
def check(cfg: EksConfig, event: dict, *, dry_run: bool, context) -> dict:
    problems: dict[str, dict] = {}
    fatal: dict[str, dict] = {}

    for cluster in cfg.clusters:
        found: dict[str, object] = {}
        apis = _build_apis(cfg, cluster)

        ns_names = [ns.name for ns in cluster.namespaces]
        if deployments := _deployment_problems(apis, ns_names):
            found["deployments"] = deployments
        daemonsets, ds_fatal = _daemonset_problems(apis, ns_names)
        if daemonsets:
            found["daemonsets"] = daemonsets
        if ds_fatal:
            fatal[cluster.name] = {"daemonsets": ds_fatal}
        if pending := _pending_pods(apis, ns_names):
            found["pending_pods"] = pending

        if found:
            problems[cluster.name] = found

    if fatal:
        raise NotRecoverableError(
            json.dumps({"workload": fatal}, ensure_ascii=False, default=str))
    return problems


# kubectl rollout restart が付けるアノテーション。値を更新すると Pod テンプレート
# のハッシュが変わり、ローリングアップデートが走る。
RESTART_ANNOTATION = "kubectl.kubernetes.io/restartedAt"

# rollout restart に対応する種別と、対応する patch メソッド名。
RESTART_METHODS = {
    "Deployment": "patch_namespaced_deployment",
    "DaemonSet": "patch_namespaced_daemon_set",
}


def _rollout_restart(apis: ClusterApis, cluster: ClusterConfig, *,
                     dry_run: bool) -> None:
    """設定された対象に kubectl rollout restart 相当を実行する.

    kubectl rollout restart deployment/<name> -n <ns> に相当。
    kubectl はテンプレートの annotations に restartedAt を書き込むだけで、
    実際の Pod 入れ替えはコントローラが行う。ここでも同じ patch を送る。

    完了は待たない。収束は check（readyReplicas >= spec.replicas）が
    確認する。待機を Lambda ではなく Step Functions の Retry に任せる。
    """
    now = datetime.now(UTC).isoformat()
    body = {"spec": {"template": {"metadata": {
        "annotations": {RESTART_ANNOTATION: now}}}}}

    for ns in cluster.namespaces:
        for target in ns.restart_targets:
            method = RESTART_METHODS.get(target.kind)
            if method is None:
                raise NotRecoverableError(
                    f"unsupported restart kind: {target.kind} "
                    f"(supported: {sorted(RESTART_METHODS)})")

            label = f"{cluster.name}/{ns.name}/{target.kind}/{target.name}"
            if dry_run:
                logger.info("would rollout restart: %s", label)
                continue
            getattr(apis.apps, method)(
                target.name, ns.name, body, _request_timeout=K8S_TIMEOUT)
            logger.info("rollout restart: %s", label)


@lambda_handler("eks-rollout-restart", EksConfig)
def rollout_restart(cfg: EksConfig, event: dict, *, dry_run: bool,
                    context) -> dict:
    """設定された対象を rollout restart する.

    既存の Pod 再起動 Lambda を呼ぶ restart_pods とは別系統。こちらは
    Kubernetes API を直接叩くため、呼び出し先の実装に依存しない。

    対象は NamespaceConfig.restart_targets で指定する。空なら何もしない
    （その namespace は check の対象にはなる）。

    必要な Kubernetes RBAC は deployments / daemonsets への patch。
    check 用の list だけでは足りない。
    """
    for cluster in cfg.clusters:
        if not any(ns.restart_targets for ns in cluster.namespaces):
            continue
        apis = _build_apis(cfg, cluster)
        _rollout_restart(apis, cluster, dry_run=dry_run)
    return {}


def _invoke_config(timeout: int) -> Config:
    """Pod 再起動 Lambda を同期呼び出しするための Config を返す.

    BOTO_CONFIG の read_timeout=10 秒では、呼ばれる側が Pod の起動完了を
    待つ実装のため足りない。呼ばれる側の Timeout に合わせて
    POD_RESTART_TIMEOUT で設定する。

    リトライは行わない。呼ばれる側が冪等とは限らないので、同じ再起動が
    二重に走るのを避ける。
    """
    return Config(
        connect_timeout=5,
        read_timeout=timeout,
        retries={"mode": "standard", "max_attempts": 0},
    )


def _invoke_restart(lam, name: str, *, dry_run: bool) -> None:
    """Pod 再起動 Lambda を 1 つ同期呼び出しする.

    aws lambda invoke --function-name <name> --invocation-type RequestResponse
      の StatusCode / FunctionError に相当。

    FunctionError が返る場合は呼ばれた側が例外で終了している。応答本文に
    エラーの詳細が入るので、そのまま記録して失敗として扱う。
    """
    if dry_run:
        logger.info("would invoke pod restart function: %s", name)
        return

    response = lam.invoke(FunctionName=name, InvocationType="RequestResponse")
    error = response.get("FunctionError")
    if error:
        payload = response["Payload"].read().decode("utf-8", errors="replace")
        msg = f"{name}: {error}: {payload[:500]}"
        raise NotRecoverableError(msg)

    logger.info("pod restart invoked: %s status=%s",
                name, response.get("StatusCode"))


@lambda_handler("eks-restart-pods", EksConfig)
def restart_pods(cfg: EksConfig, event: dict, *, dry_run: bool, context) -> dict:
    """既存の Pod 再起動 Lambda を並列に呼び出す.

    対象クラスタ・namespace・Pod は呼ばれる側が保持しているため、こちらは
    関数名のリストを実行するだけ。順序依存が無いので並列に投げる。
    呼ばれる側は Pod の起動完了を待つため、逐次だと本数ぶん時間が積み上がる。

    **全件を投げてから結果を集める。** 途中で失敗しても他は既に走っている
    ので、中断はできない。失敗が 1 件でもあれば NotRecoverableError を
    送出し、どの関数が失敗したかをすべて載せる。
    """
    lam = client("lambda", cfg.region, _invoke_config(cfg.pod_restart_timeout))
    names = cfg.pod_restart_functions
    if not names:
        return {}

    failures: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        futures = {pool.submit(_invoke_restart, lam, name, dry_run=dry_run): name
                   for name in names}
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001 - 全件の結果を集めるため
                failures[name] = f"{type(exc).__name__}: {exc}"

    if failures:
        raise NotRecoverableError(
            json.dumps({"pod_restart": failures}, ensure_ascii=False,
                       default=str))
    return {}
