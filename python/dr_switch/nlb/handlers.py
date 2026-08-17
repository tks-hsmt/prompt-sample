"""NLB の登録済みターゲットが健全か確認する.

判定は unhealthy 系 == 0 かつ 遷移中 == 0 かつ healthy >= 1。
登録済みのターゲットが健全かだけを見る（必要数の判定は行わない）。

必要な IAM:
    elasticloadbalancing:DescribeTargetHealth

ハンドラ（成功時は何も返さない。失敗・未収束は例外で表現する）:
    check   入力 {"dry_run": bool}。成功時は何も返さない。未収束は例外で表現する
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dr_switch.core import client, lambda_handler
from dr_switch.nlb.config import NlbConfig

if TYPE_CHECKING:
    from mypy_boto3_elbv2.literals import TargetHealthStateEnumType

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

    return problems
