"""dr-check-nlb: 新 ACTIVE 側の NLB ターゲットが健全か確認する.

===========================================================================
必要な IAM 権限
---------------------------------------------------------------------------
    elasticloadbalancing:DescribeTargetHealth   *   （リソースレベル指定不可）

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
必要数を外から与える設定は持たない。Deployment 自身が spec.replicas を
持っており、設定と実態がずれる余地を作らないため。

initial（登録処理が進行中）を許容しないのは、早すぎる開放を防ぐため。
EndpointSlice の更新は ELB のターゲット登録より速く進むので、Pod が Ready
でも NLB 側が initial のままの時間がある。

Hybrid Node の Ready 状態や Pending 状態の Pod はターゲットグループに
現れないため、dr-check-workload との併用が前提。

入力 : {}
出力 : 正常時は無し / 未収束なら RetryableError
"""

from __future__ import annotations

from aws import client
from config import NlbConfig
from handlers import check_handler


@check_handler("nlb", NlbConfig)
def handler(cfg: NlbConfig) -> dict:
    elb = client("elbv2", cfg.region)
    problems: dict[str, dict] = {}

    for arn in cfg.target_group_arns:
        states = [
            desc["TargetHealth"]["State"]
            for desc in elb.describe_target_health(
                TargetGroupArn=arn)["TargetHealthDescriptions"]
        ]
        healthy = states.count("healthy")
        initial = states.count("initial")
        unhealthy = states.count("unhealthy")

        if unhealthy or initial or healthy < 1:
            problems[arn] = {
                "healthy": healthy, "initial": initial, "unhealthy": unhealthy,
                "other": len(states) - healthy - initial - unhealthy,
            }

    return problems
