"""dr-check-workload: 新 ACTIVE 側（SELF）の EKS Pod / Hybrid Node を確認する.

check_readiness と分けている理由:
    このハンドラは Kubernetes API へ到達するため VPC 内配置が必要で、
    kubernetes ライブラリを同梱するため Layer もしくはコンテナイメージになる。
    AWS API を叩くだけの readiness チェックまで VPC / NAT に依存させると
    障害時の失敗点が増えるため、意図的に別関数にしている。

前提:
    - Lambda 実行ロールを EKS アクセスエントリ（または aws-auth）で
      view 相当にマッピングしておくこと。
    - この権限設定は訓練時にしか使われないため、dry_run の定期実行で
      平時から検証しておくのが望ましい。

入力:
    {}

出力:
    {"ready": true/false, "detail": {...}}
    readiness と同じく例外は投げず結果を返す。
"""

import base64
import os
import tempfile

import boto3
from botocore.signers import RequestSigner
from kubernetes import client as k8s

from common import client, config

TOKEN_TTL_SEC = 60


def _guard(fn, *args, **kwargs) -> dict:
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _eks_token(cluster_name: str, region: str) -> str:
    """aws-iam-authenticator と同方式（STS GetCallerIdentity の署名付き URL）."""
    session = boto3.session.Session(region_name=region)
    signer = RequestSigner("sts", region, "sts", "v4",
                           session.get_credentials(), session.events)
    params = {
        "method": "GET",
        "url": (f"https://sts.{region}.amazonaws.com/"
                "?Action=GetCallerIdentity&Version=2011-06-15"),
        "body": {},
        "headers": {"x-k8s-aws-id": cluster_name},
        "context": {},
    }
    signed = signer.generate_presigned_url(
        params, region_name=region, expires_in=TOKEN_TTL_SEC, operation_name="")
    encoded = base64.urlsafe_b64encode(signed.encode()).decode().rstrip("=")
    return "k8s-aws-v1." + encoded


def _k8s_clients(cfg: dict):
    region, cluster = cfg["region"], cfg["eks_cluster_name"]
    eks = client("eks", region)
    described = eks.describe_cluster(name=cluster)["cluster"]

    ca_path = os.path.join(tempfile.gettempdir(), f"{cluster}-ca.crt")
    with open(ca_path, "wb") as fh:
        fh.write(base64.b64decode(described["certificateAuthority"]["data"]))

    conf = k8s.Configuration()
    conf.host = described["endpoint"]
    conf.ssl_ca_cert = ca_path
    conf.api_key = {"authorization": "Bearer " + _eks_token(cluster, region)}
    api_client = k8s.ApiClient(conf)
    return k8s.CoreV1Api(api_client), k8s.AppsV1Api(api_client)


def check_deployments(apps_api, cfg: dict) -> dict:
    """readyReplicas で判定する。replicas（作成済み数）では
    Pod が起動しただけの状態を通してしまう。

    期待値は東京と同数を前提にしている（縮退運転はしない構成）。
    """
    result, all_ok = {}, True
    for key, want in cfg["eks_deployments"].items():
        namespace, name = key.split("/", 1)
        status = apps_api.read_namespaced_deployment_status(
            name, namespace).status
        ready = status.ready_replicas or 0
        ok = ready >= int(want)
        result[key] = {"ready": ready, "want": int(want), "ok": ok}
        all_ok = all_ok and ok
    return {"ok": all_ok, "deployments": result}


def check_nodes(core_api, cfg: dict) -> dict:
    """Hybrid Node の Ready は Direct Connect 経路の生死をそのまま反映する。
    オンプレ側を直接叩かなくても、大阪クラスタの API から判定できる。
    """
    nodes = core_api.list_node(label_selector=cfg["hybrid_node_selector"]).items
    detail, ready_count = {}, 0
    for node in nodes:
        ready = any(c.type == "Ready" and c.status == "True"
                    for c in (node.status.conditions or []))
        detail[node.metadata.name] = ready
        ready_count += int(ready)
    return {"ok": bool(nodes) and ready_count == len(nodes),
            "total": len(nodes), "ready": ready_count, "nodes": detail}


def check_pending_pods(core_api, cfg: dict) -> dict:
    """Pending の Pod はノードキャパシティ不足のサイン。"""
    pending, total = [], 0
    for namespace in cfg["eks_namespaces"]:
        for pod in core_api.list_namespaced_pod(namespace).items:
            total += 1
            if pod.status.phase == "Pending":
                pending.append(f"{namespace}/{pod.metadata.name}")
    return {"ok": not pending, "total_pods": total, "pending": pending}


def handler(event, context):
    cfg = config("self")
    try:
        core_api, apps_api = _k8s_clients(cfg)
    except Exception as exc:  # noqa: BLE001
        return {"check": "workload", "region": cfg["region"], "ready": False,
                "detail": {"cluster": {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}"}}}

    detail = {
        "deployments": _guard(check_deployments, apps_api, cfg),
        "hybrid_nodes": _guard(check_nodes, core_api, cfg),
        "pending_pods": _guard(check_pending_pods, core_api, cfg),
    }
    return {
        "check": "workload",
        "region": cfg["region"],
        "ready": all(v.get("ok") for v in detail.values()),
        "detail": detail,
    }
