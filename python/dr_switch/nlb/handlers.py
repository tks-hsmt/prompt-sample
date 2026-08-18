"""NLB がトラフィックを受けられる状態か確認する.

ロードバランサ自体の状態と、登録済みターゲットの健全性を見る。
ターゲットの判定は unhealthy 系 == 0 かつ 遷移中 == 0 かつ healthy >= 1。
必要数の判定は行わない。

必要な IAM:
    elasticloadbalancing:DescribeLoadBalancers
    elasticloadbalancing:DescribeTargetHealth

ハンドラ（成功時は何も返さない。失敗・未収束は例外で表現する）:
    check   入力 {"dry_run": bool}。成功時は何も返さない。未収束は例外で表現する
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from dr_switch.core import NotRecoverableError, client, lambda_handler
from dr_switch.nlb.config import NlbConfig

if TYPE_CHECKING:
    from mypy_boto3_elbv2.literals import (
        LoadBalancerStateEnumType,
        TargetHealthStateEnumType,
    )

# LoadBalancer.State.Code の分類。公式の説明は次の通り。
#   provisioning    … 初期状態。セットアップ中
#   active          … セットアップ完了。トラフィックをルーティングできる
#   active_impaired … ルーティングはしているがスケールに必要なリソースが不足
#   failed          … セットアップに失敗した
# active_impaired はトラフィックを流せるが不安定なので、待てば直る側に置く。
HEALTHY_LB_STATES: frozenset[LoadBalancerStateEnumType] = frozenset({"active"})
TRANSIENT_LB_STATES: frozenset[LoadBalancerStateEnumType] = frozenset({
    "provisioning", "active_impaired",
})

# TargetHealth.State の分類。値は boto3-stubs の TargetHealthStateEnumType に対応。
HEALTHY_TARGET_STATES: frozenset[TargetHealthStateEnumType] = frozenset({"healthy"})
# 登録処理・登録解除処理の途中。時間が経てば healthy か対象外になる。
TRANSIENT_TARGET_STATES: frozenset[TargetHealthStateEnumType] = frozenset({
    "initial", "draining", "unhealthy.draining",
})
# ヘルスチェックに失敗、または LB から使われていない状態。
UNHEALTHY_TARGET_STATES: frozenset[TargetHealthStateEnumType] = frozenset({
    "unhealthy", "unused", "unavailable",
})


@lambda_handler("nlb-check", NlbConfig)
def check(cfg: NlbConfig, event: dict, *, dry_run: bool, context) -> dict:
    elb = client("elbv2", cfg.region)
    problems: dict[str, dict] = {}
    fatal: dict[str, dict] = {}

    if cfg.load_balancer_arns:
        # aws elbv2 describe-load-balancers --load-balancer-arns <arn>
        #   の LoadBalancers[].State.Code
        for lb in elb.describe_load_balancers(
                LoadBalancerArns=cfg.load_balancer_arns)["LoadBalancers"]:
            code = lb["State"]["Code"]
            if code in HEALTHY_LB_STATES:
                continue
            detail = {"state": code, "reason": lb["State"].get("Reason")}
            target = problems if code in TRANSIENT_LB_STATES else fatal
            target[lb["LoadBalancerArn"]] = detail

    for arn in cfg.target_group_arns:
        # aws elbv2 describe-target-health --target-group-arn <arn>
        #   の TargetHealthDescriptions[].TargetHealth.State
        states = [
            desc["TargetHealth"]["State"]
            for desc in elb.describe_target_health(
                TargetGroupArn=arn)["TargetHealthDescriptions"]
        ]
        healthy = sum(s in HEALTHY_TARGET_STATES for s in states)
        transient = sum(s in TRANSIENT_TARGET_STATES for s in states)
        unhealthy = sum(s in UNHEALTHY_TARGET_STATES for s in states)

        if unhealthy or transient or healthy < 1:
            problems[arn] = {
                "healthy": healthy, "transient": transient,
                "unhealthy": unhealthy,
                "states": sorted(set(states)),
            }

    if fatal:
        raise NotRecoverableError(
            json.dumps({"nlb": fatal}, ensure_ascii=False, default=str))
    return problems
