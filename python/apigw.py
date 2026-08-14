"""dr-apigw: API Gateway の閉塞 / 開放（REST API・execute-api 直利用）.

===========================================================================
必要な IAM 権限
---------------------------------------------------------------------------
    apigateway:GET / PATCH / POST / UpdateRestApiPolicy
        arn:aws:apigateway:<両リージョン>::/restapis/<id> と配下

    ※ role を引数で受けるため PEER / SELF 両リージョンの ARN が必要。
    ※ カスタムドメインを使っていないため、execute-api のリソースポリシーが
      唯一の確実な閉塞手段。ドメインマッピング削除は選択肢にならない。
===========================================================================

入力 : {"role": "self"|"peer", "blocked": true|false, "dry_run": false}
出力 : {"action": "apigw", "role": ..., "region": ..., "changed": bool, ...}

例外 : RetryableError   -> Retry
       ContinuableError -> Catch（role=peer の恒久エラー）
       その他           -> 未捕捉 = ワークフロー停止（role=self の恒久エラー）
"""

from __future__ import annotations

import json

from common import (
    AWS_ERRORS,
    RegionConfig,
    client,
    get_logger,
    ops_handler,
    raise_classified,
)

logger = get_logger(__name__)

DENY_SID = "DRFenceDenyAll"
ALLOW_SID = "DRAllowInvoke"


def _build_policy(execute_api_arn: str, *, blocked: bool) -> dict:
    """目標状態のポリシーを毎回ゼロから組み立てる（冪等）.

    既存ポリシーを読んで加工する方式にすると、読み取り時のエスケープ差異や
    途中で失敗した中間状態を引きずるため、望ましい状態を宣言的に書き込む。
    """
    statements = [{
        "Sid": ALLOW_SID, "Effect": "Allow", "Principal": "*",
        "Action": "execute-api:Invoke", "Resource": execute_api_arn,
    }]
    if blocked:
        # Deny は Allow に優先する。1 件も通さない閉塞。
        statements.append({
            "Sid": DENY_SID, "Effect": "Deny", "Principal": "*",
            "Action": "execute-api:Invoke", "Resource": execute_api_arn,
        })
    return {"Version": "2012-10-17", "Statement": statements}


def _parse_policy(raw: str | None) -> dict:
    """get_rest_api が返すポリシー文字列を読む.

    ダブルクオートがエスケープされた形で返ることがあるため、素直な
    パースを先に試し、失敗した場合のみアンエスケープを試みる。
    無条件に replace すると正当なエスケープまで壊す。
    """
    if not raw:
        return {}
    for candidate in (raw, raw.replace('\\"', '"')):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    logger.warning("could not parse existing resource policy")
    return {}


@ops_handler("apigw")
def handler(cfg: RegionConfig, event: dict, *, dry_run: bool, context) -> dict:
    """リソースポリシーを書き換えて再デプロイする.

    リソースポリシーの変更は再デプロイしないと反映されない（AWS 公式）。
    update_rest_api の後に create_deployment を必ず実行する。
    """
    blocked = bool(event["blocked"])
    # STS を呼ばずに Lambda の ARN からアカウント ID を取り出す
    account = context.invoked_function_arn.split(":")[4]
    arn = f"arn:aws:execute-api:{cfg.region}:{account}:{cfg.rest_api_id}/*"
    apigw = client("apigateway", cfg.region)

    try:
        current = _parse_policy(
            apigw.get_rest_api(restApiId=cfg.rest_api_id).get("policy"))
        already = any(stmt.get("Sid") == DENY_SID
                      for stmt in current.get("Statement", []))

        if already == blocked:
            # 既に目標状態。再デプロイもしない（冪等）。
            return {"changed": False, "blocked": blocked,
                    "reason": "already in desired state"}

        if dry_run:
            return {"changed": False, "blocked": blocked,
                    "would": f"set policy blocked={blocked}, redeploy {cfg.stage}"}

        apigw.update_rest_api(
            restApiId=cfg.rest_api_id,
            patchOperations=[{
                "op": "replace", "path": "/policy",
                "value": json.dumps(_build_policy(arn, blocked=blocked)),
            }],
        )
        deployment = apigw.create_deployment(
            restApiId=cfg.rest_api_id, stageName=cfg.stage,
            description=f"DR switch: blocked={blocked}",
        )
    except AWS_ERRORS as exc:
        raise_classified(exc, role=cfg.role,
                         what=f"apigw({cfg.role}:{cfg.rest_api_id})")

    return {"changed": True, "blocked": blocked,
            "deployment_id": deployment["id"]}
