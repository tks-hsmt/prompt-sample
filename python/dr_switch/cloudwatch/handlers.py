"""ALARM 状態のアラームが無いか確認する.

リソース個別チェックで拾えない異常を包括的にカバーする。
ALARM_PREFIX を設定して自チームのアラームだけに絞ること。

必要な IAM:
    cloudwatch:DescribeAlarms

ハンドラ（成功時は何も返さない。失敗・未収束は例外で表現する）:
    check   入力 {"dry_run": bool}。成功時は何も返さない。未収束は例外で表現する
"""

from __future__ import annotations

from dr_switch.cloudwatch.config import AlarmConfig
from dr_switch.core import client, lambda_handler


@lambda_handler("cloudwatch-check", AlarmConfig)
def check(cfg: AlarmConfig, event: dict, *, dry_run: bool, context) -> dict:
    # aws cloudwatch describe-alarms --state-value ALARM --alarm-name-prefix <p>
    #   の MetricAlarms[].AlarmName
    cw = client("cloudwatch", cfg.region)
    kwargs: dict = {"StateValue": "ALARM"}
    if cfg.alarm_prefix:
        kwargs["AlarmNamePrefix"] = cfg.alarm_prefix

    # 既定では 100 件で無言に打ち切られるためページネータを使う
    paginator = cw.get_paginator("describe_alarms")
    in_alarm = [alarm["AlarmName"]
                for page in paginator.paginate(**kwargs)
                for alarm in page["MetricAlarms"]]
    return {"in_alarm": in_alarm} if in_alarm else {}
