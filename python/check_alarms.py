"""dr-check-alarms: 新 ACTIVE 側に ALARM 状態のアラームが無いか確認する.

===========================================================================
必要な IAM 権限（この Lambda のみ）
---------------------------------------------------------------------------
    cloudwatch:DescribeAlarms   *  （リソースレベル指定不可）

    ※ SELF リージョンのみ。読み取り専用。
===========================================================================

リソース個別チェックで拾えない異常を包括的にカバーする。
ALARM_PREFIX を設定して自チームのアラームだけに絞ること。

入力 : {}
出力 : {"check": "alarms", "region": "...", "ready": bool, "detail": {...}}
"""

from __future__ import annotations

from common import RegionConfig, check_result, client, config, guard


def check_alarms(cfg: RegionConfig) -> dict:
    cw = client("cloudwatch", cfg.region)
    kwargs: dict = {"StateValue": "ALARM"}
    if cfg.alarm_prefix:
        kwargs["AlarmNamePrefix"] = cfg.alarm_prefix
    in_alarm = [alarm["AlarmName"]
                for alarm in cw.describe_alarms(**kwargs).get("MetricAlarms", [])]
    return {"ok": not in_alarm, "in_alarm": in_alarm}


def handler(event: dict, context) -> dict:
    cfg = config("self")
    return check_result("alarms", cfg.region,
                        {"alarms": guard("alarms", check_alarms, cfg)})
