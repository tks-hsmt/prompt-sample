"""dr-check-nlb: 新 ACTIVE 側の NLB ターゲットが健全か確認する.

===========================================================================
必要な IAM 権限（この Lambda のみ）
---------------------------------------------------------------------------
    elasticloadbalancing:DescribeTargetHealth   *  （リソースレベル指定不可）
    elasticloadbalancing:DescribeTargetGroups   *

    ※ SELF リージョンのみ。読み取り専用。
===========================================================================

【構成】NLB とターゲットグループは AWS Load Balancer Controller が Service
から作成。ターゲットタイプは IP、トラフィック・ヘルスチェックとも TCP で、
HealthCheckPort は traffic-port（トラフィックポートと同一番号）。

IP モードでは NLB が Pod IP へ直接トラフィックを送るため、トラフィックは
kube-proxy を経由せず、externalTrafficPolicy は判定に関係しない。
Controller は Endpoints / EndpointSlices からターゲットを解決し、一覧に無い
ターゲットは即座に登録解除する。したがって

    登録されているターゲット ≒ Ready な Pod

【判定】このチェックは「登録済みのターゲットがすべて健全か」だけを見る。

    unhealthy == 0  かつ  initial == 0  かつ  healthy >= 1

必要数を満たしているかの判定は dr-check-workload に一本化している。
必要数を外から与える設定（MIN_HEALTHY_TARGETS）は持たない。Deployment 自身が
spec.replicas を持っており、設定と実態がずれる余地を作らないため。

    initial（登録処理が進行中）を許容しないのは、早すぎる開放を防ぐため。
    EndpointSlice の更新は ELB のターゲット登録より速く進むので、Pod が
    Ready でも NLB 側が initial のままの時間がある。

Step Functions の Choice は dr-check-nlb と dr-check-workload の両方が
ready: true であることを条件にすること。Hybrid Node の Ready 状態や
Pending 状態の Pod はターゲットグループに現れないため、こちらだけでは
判定材料が足りない。

入力 : {}
出力 : {"check": "nlb", "region": "...", "ready": bool, "detail": {...}}
"""

from __future__ import annotations

from common import RegionConfig, check_result, client, config, guard


def check_nlb(cfg: RegionConfig) -> dict:
    elb = client("elbv2", cfg.region)
    groups = {}

    if not cfg.target_group_arns:
        return {"ok": False, "error": "TARGET_GROUP_ARNS is empty"}

    described = elb.describe_target_groups(
        TargetGroupArns=cfg.target_group_arns)["TargetGroups"]
    attributes = {
        tg["TargetGroupArn"]: {
            "target_type": tg.get("TargetType"),
            "health_check_protocol": tg.get("HealthCheckProtocol"),
        }
        for tg in described
    }

    for arn in cfg.target_group_arns:
        states = [
            desc["TargetHealth"]["State"]
            for desc in elb.describe_target_health(
                TargetGroupArn=arn)["TargetHealthDescriptions"]
        ]
        healthy = states.count("healthy")
        initial = states.count("initial")
        unhealthy = states.count("unhealthy")
        groups[arn] = {
            "healthy": healthy,
            "initial": initial,
            "unhealthy": unhealthy,
            "other": len(states) - healthy - initial - unhealthy,
            **attributes.get(arn, {}),
            "ok": unhealthy == 0 and initial == 0 and healthy >= 1,
        }

    return {"ok": all(g["ok"] for g in groups.values()), "target_groups": groups}


def handler(event: dict, context) -> dict:
    cfg = config("self")
    result = check_result("nlb", cfg.region,
                          {"nlb": guard("nlb", check_nlb, cfg)})
    # 必要数の判定・Hybrid Node・Pending Pod はここでは見えない。
    # 呼び出し側（Step Functions）が併用を忘れないよう戻り値に明示する。
    result["requires"] = "dr-check-workload"
    return result
