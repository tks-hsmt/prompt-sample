"""dr-check-workload: 新 ACTIVE 側の EKS Pod / Hybrid Node を確認する.

===========================================================================
必要な IAM 権限
---------------------------------------------------------------------------
    eks:DescribeCluster     arn:aws:eks:<SELF>:<acct>:cluster/<クラスタ名>
    sts:GetCallerIdentity   *   （kubeconfig の exec プラグインが使用）

    ※ AWS 側の権限はこれだけ。Pod / Node の参照権限は IAM ではなく
      Kubernetes RBAC 側（EKS アクセスエントリで view 相当にマッピング）。
    ※ 既存の Pod 再起動 Lambda と同じロール設計を流用できる。
===========================================================================

接続方式:
    既に本番稼働している Pod 再起動 Lambda と同じ方式を踏襲する。
    AWS CLI の `aws eks update-kubeconfig` で kubeconfig を生成し、
    kubernetes クライアントにそれを読ませる。CA 証明書とトークン取得は
    すべて CLI が肩代わりするため、Python 側の実装は不要。
        - certificate-authority-data … update-kubeconfig が kubeconfig に書く
        - Bearer トークン              … exec プラグインが aws eks get-token を
                                         都度実行して取得

タイムアウト:
    update-kubeconfig は 15 秒、Kubernetes API 呼び出しは (connect 3, read 10) 秒。
    応答しない相手を待ち続けて RTO を消費しないようにする。

前提:
    - クラスタ API エンドポイントはプライベートのみのため、到達可能な
      VPC・サブネット・セキュリティグループに配置する（既存 Lambda と同じ）
    - コンテナイメージに AWS CLI と kubernetes パッケージを同梱する

入力 : {}
出力 : 正常時は無し / 未収束なら RetryableError
"""

from __future__ import annotations

import os
import subprocess

from kubernetes import client as k8s
from kubernetes import config as k8s_config

from config import EksConfig
from handlers import check_handler
from logging_json import get_logger

logger = get_logger(__name__)

KUBECONFIG_PATH = "/tmp/kubeconfig"  # noqa: S108 - Lambda で書けるのは /tmp のみ
AWS_CLI = os.environ.get("AWS_CLI_PATH", "aws")
UPDATE_KUBECONFIG_TIMEOUT_SEC = 15
# Kubernetes API 呼び出しのタイムアウト (connect, read)。
# 応答しないクラスタを待ち続けて RTO を消費しないようにする。
K8S_TIMEOUT = (3, 10)


def _build_clients(cfg: EksConfig) -> tuple[k8s.CoreV1Api, k8s.AppsV1Api]:
    # HOME はベースイメージ側で設定されている可能性があるため無条件に上書きする。
    # setdefault だと既存値が残り、AWS CLI が書き込めないパスへキャッシュを
    # 作ろうとして失敗する。Lambda で書けるのは /tmp のみ。
    os.environ["HOME"] = "/tmp"  # noqa: S108
    os.environ["KUBECONFIG"] = KUBECONFIG_PATH

    # 毎回生成する。ウォームスタート時に再利用する実装にすると、生成が
    # 途中で失敗した場合に不完全なファイルが残り、そのコンテナが生きている
    # 間ずっと壊れ続ける。コストは DescribeCluster 1 回分で、
    # タイムアウトで上限を切れる。
    subprocess.run(  # noqa: S603
        [AWS_CLI, "eks", "update-kubeconfig",
         "--name", cfg.cluster_name,
         "--region", cfg.region,
         "--kubeconfig", KUBECONFIG_PATH],
        check=True, capture_output=True,
        timeout=UPDATE_KUBECONFIG_TIMEOUT_SEC,
    )

    k8s_config.load_kube_config(config_file=KUBECONFIG_PATH)
    return k8s.CoreV1Api(), k8s.AppsV1Api()


def _unconverged_deployments(apps_api: k8s.AppsV1Api, cfg: EksConfig) -> dict:
    """各 Deployment が自身の spec.replicas に収束しているかを判定する.

    必要数は Deployment 自身が spec.replicas として持っているため、設定値と
    して外から与えない。設定と実態がずれる余地がなくなり、レプリカ数を
    変えても Lambda の環境変数を直す必要がない。Deployment 名も列挙する
    ので、設定は namespace のリストだけで済む。

    status.ready_replicas で判定する。status.replicas（作成済み数）では
    Pod が起動しただけで readinessProbe を通っていない状態を通してしまう。

    検出できないもの: 「本来 3 のはずが spec.replicas が 1 になっている」
    ような平時の構成ドリフト。切替の瞬間に気づいても打つ手がないので、
    dry_run の定期実行や Terraform のドリフト検知で拾う。
    """
    unconverged = {}
    for namespace in cfg.namespaces:
        for dep in apps_api.list_namespaced_deployment(
                namespace, _request_timeout=K8S_TIMEOUT).items:
            want = dep.spec.replicas or 0
            ready = dep.status.ready_replicas or 0
            if ready < want:
                unconverged[f"{namespace}/{dep.metadata.name}"] = {
                    "ready": ready, "want": want}
    return unconverged


def _hybrid_node_problem(core_api: k8s.CoreV1Api, cfg: EksConfig) -> dict | None:
    """Hybrid Node の Ready は Direct Connect 経路の生死をそのまま反映する。
    オンプレ側を直接叩かなくても、クラスタ API から判定できる。

    「1 台も見つからない」と「Ready でない台がある」は別の異常なので、
    ノード名のリストにセンチネル文字列を混ぜず、理由を分けて返す。
    """
    nodes = core_api.list_node(label_selector=cfg.hybrid_node_selector,
                               _request_timeout=K8S_TIMEOUT).items
    if not nodes:
        return {"reason": "no hybrid node matched the selector",
                "selector": cfg.hybrid_node_selector}

    not_ready = [
        node.metadata.name for node in nodes
        if not any(cond.type == "Ready" and cond.status == "True"
                   for cond in (node.status.conditions or []))
    ]
    if not_ready:
        return {"reason": "nodes not ready", "nodes": not_ready,
                "total": len(nodes)}
    return None


def _pending_pods(core_api: k8s.CoreV1Api, cfg: EksConfig) -> list[str]:
    """Pending の Pod はノードキャパシティ不足のサイン。"""
    return [
        f"{namespace}/{pod.metadata.name}"
        for namespace in cfg.namespaces
        for pod in core_api.list_namespaced_pod(
            namespace, _request_timeout=K8S_TIMEOUT).items
        if pod.status.phase == "Pending"
    ]


@check_handler("workload", EksConfig)
def handler(cfg: EksConfig) -> dict:
    core_api, apps_api = _build_clients(cfg)

    problems: dict[str, object] = {}
    if unconverged := _unconverged_deployments(apps_api, cfg):
        problems["deployments"] = unconverged
    if node_problem := _hybrid_node_problem(core_api, cfg):
        problems["hybrid_nodes"] = node_problem
    if pending := _pending_pods(core_api, cfg):
        problems["pending_pods"] = pending

    return problems
