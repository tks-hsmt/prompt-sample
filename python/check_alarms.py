"""dr-check-alarms: 新 ACTIVE 側に ALARM 状態のアラームが無いか確認する.

===========================================================================
必要な IAM 権限
---------------------------------------------------------------------------
    cloudwatch:DescribeAlarms   *   （リソースレベル指定不可）

    ※ SELF リージョンのみ。読み取り専用。
===========================================================================

リソース個別チェックで拾えない異常を包括的にカバーする。
ALARM_PREFIX を設定して自チームのアラームだけに絞ること。

入力 : {}
出力 : 正常時は無し / 未収束なら RetryableError
"""

from __future__ import annotations

from aws import client
from config import RegionConfig
from handlers import check_handler


@check_handler("alarms")
def handler(cfg: RegionConfig) -> dict:
    cw = client("cloudwatch", cfg.region)
    kwargs: dict = {"StateValue": "ALARM"}
    if cfg.alarm_prefix:
        kwargs["AlarmNamePrefix"] = cfg.alarm_prefix

    # ページネータを使う。既定では 100 件で打ち切られ、無言で
    # 切り捨てられるため。
    paginator = cw.get_paginator("describe_alarms")
    in_alarm = [alarm["AlarmName"]
                for page in paginator.paginate(**kwargs)
                for alarm in page["MetricAlarms"]]
    return {"in_alarm": in_alarm} if in_alarm else {}
