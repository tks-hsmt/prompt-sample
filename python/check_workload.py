"""dr-check-workload: 新 ACTIVE 側（SELF）の EKS Pod / Hybrid Node を確認する.

接続方式:
    既に本番稼働している Pod 再起動 Lambda と同じ方式を踏襲する。
    AWS CLI の `aws eks update-kubeconfig` で kubeconfig を生成し、
    kubernetes クライアントにそれを読ませる。

    この方式では CA 証明書とトークン取得をすべて CLI が肩代わりする。
        - certificate-authority-data … update-kubeconfig が kubeconfig に書き込む
        - Bearer トークン              … kubeconfig の exec プラグインが
                                         `aws eks get-token` を都度実行して取得
    そのため Python 側で CA 証明書や STS 署名を扱うコードは不要になる。

===========================================================================
必要な IAM 権限（この Lambda のみ）
---------------------------------------------------------------------------
    eks:DescribeCluster   arn:aws:eks:<SELF>:<acct>:cluster/<クラスタ名>
    sts:GetCallerIdentity *   （kubeconfig の exec プラグインが使用）

    ※ AWS 側の権限はこれだけ。Pod / Node の参照権限は IAM ではなく
      Kubernetes RBAC 側（EKS アクセスエントリで view 相当にマッピング）。
    ※ 既存の Pod 再起動 Lambda と同じロール設計を流用できる。

前提（既存の Pod 再起動 Lambda と同じ構成にすること）:
    - AWS CLI と kubernetes パッケージを Layer もしくはコンテナイメージに同梱
    - クラスタ API エンドポイントはプライベートのみのため、到達可能な
      VPC・サブネット・セキュリティグループに配置する
    - 実行ロールを EKS アクセスエントリ（または aws-auth）で view 相当に
      マッピングする。この権限は訓練時にしか使われないため、定期実行で
      平時から検証しておくのが望ましい

入力:
    {}

出力:
    {"check": "workload", "region": "...", "ready": bool, "detail": {...}}
"""

from __future__ import annotations

import logging
import os
import subprocess

from kubernetes import client as k8s
from kubernetes import config as k8s_config

from common import ConfigError, RegionConfig, check_result, config, guard

logger = logging.getLogger(__name__)

# Lambda で書き込めるのは /tmp のみ。CLI は HOME 配下も参照するため合わせる。
KUBECONFIG_PATH = "/tmp/kubeconfig"  # noqa: S108
AWS_CLI = os.environ.get("AWS_CLI_PATH", "aws")
UPDATE_KUBECONFIG_TIMEOUT_SEC = 30


def build_k8s_clients(cfg: RegionConfig) -> tuple[k8s.CoreV1Api, k8s.AppsV1Api]:
    if not cfg.eks_cluster_name:
        raise ConfigError(f"{cfg.role.upper()}_EKS_CLUSTER_NAME is not set")

    os.environ.setdefault("HOME", "/tmp")  # noqa: S108
    os.environ["KUBECONFIG"] = KUBECONFIG_PATH

    # ウォームスタート時は生成済みの kubeconfig を再利用する。
    # トークンは exec プラグインが呼び出しのたびに取り直すため期限切れしない。
    if not os.path.exists(KUBECONFIG_PATH):
        subprocess.run(  # noqa: S603
            [AWS_CLI, "eks", "update-kubeconfig",
             "--name", cfg.eks_cluster_name,
             "--region", cfg.region,
             "--kubeconfig", KUBECONFIG_PATH],
            check=True,
            capture_output=True,
            timeout=UPDATE_KUBECONFIG_TIMEOUT_SEC,
        )
        logger.info("kubeconfig generated: cluster=%s region=%s",
                    cfg.eks_cluster_name, cfg.region)

    k8s_config.load_kube_config(config_file=KUBECONFIG_PATH)
    return k8s.CoreV1Api(), k8s.AppsV1Api()


def check_deployments(apps_api: k8s.AppsV1Api, cfg: RegionConfig) -> dict:
    """各 Deployment が自身の spec.replicas に収束しているかを判定する.

    必要数は Deployment 自身が spec.replicas として持っているため、
    設定値として外から与えない。設定と実態がずれる余地がなくなり、
    レプリカ数を変えても Lambda の環境変数を直す必要がない。
    Deployment 名も列挙するので、設定は namespace のリストだけで済む。

    status.ready_replicas で判定する。status.replicas（作成済み数）では
    Pod が起動しただけで readinessProbe を通っていない状態を通してしまう。

    なお「本来 3 のはずが spec.replicas が 1 になっている」ような平時の
    構成ドリフトは、この方式では検出できない。切替の瞬間に気づいても
    打つ手がない種類の問題なので、dry_run の定期実行や Terraform の
    ドリフト検知で拾う。
    """
    deployments = {}
    for namespace in cfg.eks_namespaces:
        for dep in apps_api.list_namespaced_deployment(namespace).items:
            key = f"{namespace}/{dep.metadata.name}"
            want = dep.spec.replicas or 0
            ready = dep.status.ready_replicas or 0
            deployments[key] = {"ready": ready, "want": want,
                                "ok": ready >= want}
    return {"ok": bool(deployments) and all(d["ok"] for d in deployments.values()),
            "deployments": deployments}


def check_nodes(core_api: k8s.CoreV1Api, cfg: RegionConfig) -> dict:
    """Hybrid Node の Ready は Direct Connect 経路の生死をそのまま反映する。
    オンプレ側を直接叩かなくても、クラスタ API から判定できる。
    """
    nodes = core_api.list_node(label_selector=cfg.hybrid_node_selector).items
    ready_by_node = {
        node.metadata.name: any(cond.type == "Ready" and cond.status == "True"
                                for cond in (node.status.conditions or []))
        for node in nodes
    }
    ready = sum(ready_by_node.values())
    return {"ok": bool(nodes) and ready == len(nodes),
            "total": len(nodes), "ready": ready, "nodes": ready_by_node}


def check_pending_pods(core_api: k8s.CoreV1Api, cfg: RegionConfig) -> dict:
    """Pending の Pod はノードキャパシティ不足のサイン。"""
    pending, total = [], 0
    for namespace in cfg.eks_namespaces:
        for pod in core_api.list_namespaced_pod(namespace).items:
            total += 1
            if pod.status.phase == "Pending":
                pending.append(f"{namespace}/{pod.metadata.name}")
    return {"ok": not pending, "total_pods": total, "pending": pending}


def handler(event: dict, context) -> dict:
    cfg = config("self")

    try:
        core_api, apps_api = build_k8s_clients(cfg)
    except subprocess.CalledProcessError as exc:
        logger.exception("update-kubeconfig failed")
        return check_result("workload", cfg.region, {
            "cluster": {"ok": False,
                        "error": f"update-kubeconfig failed: "
                                 f"{exc.stderr.decode(errors='replace')[:500]}"},
        })
    except Exception as exc:  # noqa: BLE001 - 観測系は何があっても結果を返す
        logger.exception("could not reach the cluster API")
        return check_result("workload", cfg.region, {
            "cluster": {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
        })

    detail = {
        "deployments": guard("deployments", check_deployments, apps_api, cfg),
        "hybrid_nodes": guard("hybrid_nodes", check_nodes, core_api, cfg),
        "pending_pods": guard("pending_pods", check_pending_pods, core_api, cfg),
    }
    return check_result("workload", cfg.region, detail)
