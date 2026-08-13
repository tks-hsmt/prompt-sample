"""dr-check-readiness: 新 ACTIVE 側（SELF）の受け皿を確認する.

判定は SELF リージョンだけで完結する。PEER が落ちていても実行できる
（PEER の状態は切替可否に影響しない = 状態を引き継ぐリソースが無い）。

入力:
    {}                      # SELF 固定。引数不要。

出力:
    {"ready": true/false, "detail": {...}}

    合否は返すが例外は投げない。判定と分岐は Step Functions の Choice に任せる。
    個々のチェックも独立して try/except する。1 つの API エラーで全項目が
    見えなくなると、保守者が原因を切り分けられないため。

対象:
    API GW    : 開放が効いたか（ステージ + 実 HTTPS リクエスト）
    Lambda    : State / LastUpdateStatus / イベントソースマッピング
    DynamoDB  : TableStatus == ACTIVE
    NLB       : healthy 数 >= 必要数（initial は健全に数えない）
    CloudWatch: ALARM 状態のアラームが無いこと
"""

import urllib.error
import urllib.request

from common import client, config

HEALTH_TIMEOUT_SEC = 5


def _guard(fn, *args, **kwargs) -> dict:
    """個別チェックを隔離する。失敗は結果に含めるだけで送出しない。"""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def check_apigw(cfg: dict) -> dict:
    region = cfg["region"]
    apigw = client("apigateway", region)
    stage = apigw.get_stage(restApiId=cfg["rest_api_id"], stageName=cfg["stage"])

    detail = {
        "deployment_id": stage.get("deploymentId"),
        "last_updated": str(stage.get("lastUpdatedDate")),
    }

    # コントロールプレーンの設定確認だけでは「設定は正しいが通らない」を
    # 検出できない。保守経路のヘルスチェックパスへ実リクエストを 1 発投げる。
    # （NE 機器への誤警報にならない経路であること）
    url = cfg.get("health_url")
    if not url:
        detail["http"] = "skipped (no health_url configured)"
        return {"ok": True, **detail}

    try:
        with urllib.request.urlopen(url, timeout=HEALTH_TIMEOUT_SEC) as res:
            code = res.status
    except urllib.error.HTTPError as exc:
        code = exc.code
    detail["http_status"] = code
    return {"ok": code == 200, **detail}


def check_lambda(cfg: dict) -> dict:
    region = cfg["region"]
    lam = client("lambda", region)
    functions, all_ok = {}, True

    for name in cfg["function_names"]:
        conf = lam.get_function(FunctionName=name)["Configuration"]
        ok = (conf.get("State") == "Active"
              and conf.get("LastUpdateStatus") == "Successful")

        # SQS を消費するイベントソースマッピングが有効か
        mappings = lam.list_event_source_mappings(FunctionName=name)
        esm = [{"uuid": m["UUID"], "state": m["State"]}
               for m in mappings.get("EventSourceMappings", [])]
        esm_ok = all(m["state"] == "Enabled" for m in esm) if esm else True

        functions[name] = {"state": conf.get("State"),
                           "last_update": conf.get("LastUpdateStatus"),
                           "event_source_mappings": esm,
                           "ok": ok and esm_ok}
        all_ok = all_ok and ok and esm_ok

    return {"ok": all_ok, "functions": functions}


def check_dynamodb(cfg: dict) -> dict:
    # 東京・大阪でレプリケーションしない構成。リージョンごとに独立した
    # 状態を持つため、PEER の中身は確認不要。テーブルが使える状態かだけ見る。
    ddb = client("dynamodb", cfg["region"])
    tables, all_ok = {}, True
    for name in cfg["table_names"]:
        status = ddb.describe_table(TableName=name)["Table"]["TableStatus"]
        ok = status == "ACTIVE"
        tables[name] = {"status": status, "ok": ok}
        all_ok = all_ok and ok
    return {"ok": all_ok, "tables": tables}


def check_nlb(cfg: dict) -> dict:
    elb = client("elbv2", cfg["region"])
    groups, all_ok = {}, True
    minimum = cfg["min_healthy_targets"]

    for arn in cfg["target_group_arns"]:
        descs = elb.describe_target_health(TargetGroupArn=arn)
        states = [d["TargetHealth"]["State"]
                  for d in descs["TargetHealthDescriptions"]]
        healthy = states.count("healthy")
        # initial（初期チェック中）は健全に数えない。早すぎる開放を防ぐ。
        ok = healthy >= minimum
        groups[arn.split("/")[-2] if "/" in arn else arn] = {
            "healthy": healthy,
            "initial": states.count("initial"),
            "unhealthy": states.count("unhealthy"),
            "required": minimum,
            "ok": ok,
        }
        all_ok = all_ok and ok

    return {"ok": all_ok, "target_groups": groups}


def check_alarms(cfg: dict) -> dict:
    """個別チェックで拾えない異常を包括的にカバーする。"""
    cw = client("cloudwatch", cfg["region"])
    kwargs = {"StateValue": "ALARM"}
    if cfg["alarm_prefix"]:
        kwargs["AlarmNamePrefix"] = cfg["alarm_prefix"]
    alarms = cw.describe_alarms(**kwargs)
    names = [a["AlarmName"] for a in alarms.get("MetricAlarms", [])]
    return {"ok": not names, "in_alarm": names}


def handler(event, context):
    cfg = config("self")
    detail = {
        "apigw": _guard(check_apigw, cfg),
        "lambda": _guard(check_lambda, cfg),
        "dynamodb": _guard(check_dynamodb, cfg),
        "nlb": _guard(check_nlb, cfg),
        "alarms": _guard(check_alarms, cfg),
    }
    return {
        "check": "readiness",
        "region": cfg["region"],
        "ready": all(v.get("ok") for v in detail.values()),
        "detail": detail,
    }
