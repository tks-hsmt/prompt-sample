"""NLB の登録済みターゲットが健全か確認する.

判定は unhealthy == 0 かつ initial == 0 かつ healthy >= 1。
登録済みのターゲットが健全かだけを見る（必要数の判定は行わない）。

必要な IAM:
    elasticloadbalancing:DescribeTargetHealth

ハンドラ（成功時は何も返さない。失敗・未収束は例外で表現する）:
    check   入力 {"dry_run": bool}。成功時は何も返さない。未収束は例外で表現する
"""

from __future__ import annotations

from dr_switch.core import client, lambda_handler
from dr_switch.nlb.config import NlbConfig


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
        healthy = states.count("healthy")
        initial = states.count("initial")
        unhealthy = states.count("unhealthy")

        if unhealthy or initial or healthy < 1:
            problems[arn] = {
                "healthy": healthy, "initial": initial, "unhealthy": unhealthy,
                "other": len(states) - healthy - initial - unhealthy,
            }

    return problems
