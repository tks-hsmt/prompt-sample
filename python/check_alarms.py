"""dr-check-alarms: ALARM 状態のアラームが無いか確認する.

必要な IAM:
    cloudwatch:DescribeAlarms

入力 : {}   出力 : 正常時は無し / 未収束なら RetryableError
"""

from __future__ import annotations

from aws import client
from config import AlarmConfig
from handlers import check_handler


@check_handler("alarms", AlarmConfig)
def handler(cfg: AlarmConfig) -> dict:
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
