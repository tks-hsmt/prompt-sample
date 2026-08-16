"""NLB の登録済みターゲットが健全か確認する.

判定は unhealthy == 0 かつ initial == 0 かつ healthy >= 1。
登録済みのターゲットが健全かだけを見る（必要数の判定は行わない）。

必要な IAM:
    elasticloadbalancing:DescribeTargetHealth

ハンドラ:
    check   入力 {}
"""

from __future__ import annotations

from dr_switch.core import check_handler, client
from dr_switch.nlb.config import NlbConfig


@check_handler("nlb", NlbConfig)
def check(cfg: NlbConfig) -> dict:
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
        healthy = states.count("healthy")
        initial = states.count("initial")
        unhealthy = states.count("unhealthy")

        if unhealthy or initial or healthy < 1:
            problems[arn] = {
                "healthy": healthy, "initial": initial, "unhealthy": unhealthy,
                "other": len(states) - healthy - initial - unhealthy,
            }

    return problems
