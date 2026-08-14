"""dr-check-nlb: NLB の登録済みターゲットが健全か確認する.

判定は unhealthy == 0 かつ initial == 0 かつ healthy >= 1。
必要数を満たしているかの判定は dr-check-workload に一本化している。

必要な IAM:
    elasticloadbalancing:DescribeTargetHealth

入力 : {}   出力 : 正常時は無し / 未収束なら RetryableError
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
