"""API Gateway / EventBridge の閉塞・開放操作.

fence.py と activate.py が共通で使う。
"""

import json

from common import client, raise_classified

DENY_SID = "DRFenceDenyAll"
ALLOW_SID = "DRAllowInvoke"


def _build_policy(execute_api_arn: str, *, blocked: bool) -> dict:
    """目標状態のポリシーを毎回ゼロから組み立てる（冪等）.

    既存ポリシーを読んで加工する方式にすると、読み取り時のエスケープ差異や
    途中で失敗した中間状態を引きずるため、望ましい状態を宣言的に書き込む。
    """
    statements = [{
        "Sid": ALLOW_SID,
        "Effect": "Allow",
        "Principal": "*",
        "Action": "execute-api:Invoke",
        "Resource": execute_api_arn,
    }]
    if blocked:
        # Deny は Allow に優先する。1 件も通さない閉塞。
        statements.append({
            "Sid": DENY_SID,
            "Effect": "Deny",
            "Principal": "*",
            "Action": "execute-api:Invoke",
            "Resource": execute_api_arn,
        })
    return {"Version": "2012-10-17", "Statement": statements}


def _current_policy(apigw, rest_api_id: str) -> dict:
    api = apigw.get_rest_api(restApiId=rest_api_id)
    raw = api.get("policy")
    if not raw:
        return {}
    # get_rest_api はダブルクオートがエスケープされた文字列を返すことがある
    return json.loads(raw.replace('\\"', '"'))


def _is_blocked(policy: dict) -> bool:
    return any(s.get("Sid") == DENY_SID
               for s in policy.get("Statement", []))


def set_apigw(cfg: dict, account: str, *, blocked: bool, dry_run: bool) -> dict:
    """API GW を閉塞 / 開放する.

    リソースポリシーの変更は再デプロイしないと反映されないため、
    update_rest_api の後に create_deployment を必ず実行する。
    （AWS 公式: リソースポリシー更新後は API のデプロイが必要）
    """
    region, rest_api_id, stage = cfg["region"], cfg["rest_api_id"], cfg["stage"]
    arn = f"arn:aws:execute-api:{region}:{account}:{rest_api_id}/*"
    apigw = client("apigateway", region)

    try:
        current = _current_policy(apigw, rest_api_id)
        if _is_blocked(current) == blocked:
            # 既に目標状態。再デプロイもしない（冪等）。
            return {"changed": False, "blocked": blocked,
                    "reason": "already in desired state"}

        if dry_run:
            return {"changed": False, "blocked": blocked, "dry_run": True,
                    "would": f"set policy blocked={blocked} + redeploy {stage}"}

        policy = json.dumps(_build_policy(arn, blocked=blocked))
        apigw.update_rest_api(
            restApiId=rest_api_id,
            patchOperations=[{"op": "replace", "path": "/policy",
                              "value": policy}],
        )
        deployment = apigw.create_deployment(
            restApiId=rest_api_id,
            stageName=stage,
            description=f"DR switch: blocked={blocked}",
        )
        return {"changed": True, "blocked": blocked,
                "deployment_id": deployment["id"]}
    except Exception as exc:  # noqa: BLE001 - 種別は raise_classified が判定
        raise_classified(exc, role=cfg["role"],
                         what=f"apigw({cfg['role']}:{rest_api_id})")


def set_eventbridge(cfg: dict, *, enabled: bool, dry_run: bool) -> dict:
    """対象バスの全ルールを一括で有効化 / 無効化する.

    ルール名をハードコードせず list_rules で列挙する。ルール追加時に
    切替コードの更新が漏れる事故を防ぐため。
    """
    region, bus = cfg["region"], cfg["event_bus"]
    events = client("events", region)
    want = "ENABLED" if enabled else "DISABLED"
    changed, skipped = [], []

    try:
        paginator = events.get_paginator("list_rules")
        for page in paginator.paginate(EventBusName=bus):
            for rule in page["Rules"]:
                name = rule["Name"]
                if rule.get("State") == want:
                    skipped.append(name)
                    continue
                if dry_run:
                    changed.append(name)
                    continue
                if enabled:
                    events.enable_rule(Name=name, EventBusName=bus)
                else:
                    events.disable_rule(Name=name, EventBusName=bus)
                changed.append(name)
    except Exception as exc:  # noqa: BLE001
        raise_classified(exc, role=cfg["role"],
                         what=f"eventbridge({cfg['role']}:{bus})")

    return {"enabled": enabled, "changed": changed, "skipped": skipped,
            "dry_run": dry_run}
