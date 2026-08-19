"""EventBridge Scheduler スケジュールの停止 / 開始.

イベント駆動は Rules ではなく Scheduler を使うため、events ではなく
scheduler クライアントを叩く。

必要な IAM（自関数が対象とするリージョンのグループのみ）:
    scheduler:ListSchedules / GetSchedule / UpdateSchedule
    iam:PassRole  … UpdateSchedule が Target.RoleArn を要求するため必須

ハンドラ（成功時は何も返さない。失敗・未収束は例外で表現する）:
    block   スケジュールを停止。入力 {"dry_run": bool}
    enable  スケジュールを開始。入力 {"dry_run": bool}
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from dr_switch.core import (
    NotRecoverableError,
    client,
    lambda_handler,
    run_per_item,
)
from dr_switch.scheduler.config import (
    SchedulerBaseConfig,
    SchedulerBlockConfig,
    SchedulerCheckConfig,
    SchedulerEnableConfig,
)

if TYPE_CHECKING:
    from mypy_boto3_scheduler.literals import (
        ScheduleGroupStateType,
        ScheduleStateType,
    )

# 値は boto3-stubs の ScheduleStateType に対応（ENABLED / DISABLED の 2 値）。
STATE_ENABLED: ScheduleStateType = "ENABLED"
STATE_DISABLED: ScheduleStateType = "DISABLED"

# グループの状態。ACTIVE / DELETING の 2 値。DELETING は削除処理中で、
# 待っても ACTIVE には戻らない。
GROUP_ACTIVE: ScheduleGroupStateType = "ACTIVE"

# get_schedule が返すもののうち、update_schedule に渡せない読み取り専用フィールド
logger = logging.getLogger(__name__)

SCHEDULE_READONLY_KEYS = frozenset({
    "ResponseMetadata", "Arn", "CreationDate", "LastModificationDate",
})


def _set_state(scheduler, cfg: SchedulerBaseConfig, name: str,
               state: str) -> dict:
    """1 件のスケジュールの State を変更する.

    UpdateSchedule は渡した内容で丸ごと置き換える（未指定は null になる）。
    そのため get -> 読み取り専用フィールド除去 -> State 差し替え -> update
    の順で行う。
    """
    current = scheduler.get_schedule(Name=name, GroupName=cfg.schedule_group)
    params = {key: value for key, value in current.items()
              if key not in SCHEDULE_READONLY_KEYS}
    params["State"] = state
    scheduler.update_schedule(**params)
    return {"state": state}


def _set_schedules(cfg: SchedulerBaseConfig, *, enabled: bool, dry_run: bool,
                   best_effort: bool) -> None:
    scheduler = client("scheduler", cfg.region)
    want = STATE_ENABLED if enabled else STATE_DISABLED

    # aws scheduler list-schedules --group-name <g> の Schedules[].State
    paginator = scheduler.get_paginator("list_schedules")
    summaries = [summary
                 for page in paginator.paginate(GroupName=cfg.schedule_group)
                 for summary in page["Schedules"]]

    # 一覧に State が含まれるので、冪等判定に get_schedule は不要
    skipped = [s["Name"] for s in summaries if s.get("State") == want]
    targets = [s["Name"] for s in summaries if s.get("State") != want]

    def apply(name: str) -> dict:
        if dry_run:
            return {"would": f"set state to {want}"}
        return _set_state(scheduler, cfg, name, want)

    run_per_item(targets, apply, best_effort=best_effort, what="scheduler")
    logger.info("scheduler %s: group=%s changed=%d skipped=%d",
                cfg.region, cfg.schedule_group, len(targets), len(skipped))


@lambda_handler("scheduler-block", SchedulerBlockConfig, best_effort=True)
def block(cfg: SchedulerBlockConfig, event: dict, *, dry_run: bool,
          context) -> dict:
    """スケジュールを停止する。"""
    _set_schedules(cfg, enabled=False, dry_run=dry_run, best_effort=True)
    return {}


@lambda_handler("scheduler-enable", SchedulerEnableConfig)
def enable(cfg: SchedulerEnableConfig, event: dict, *, dry_run: bool,
           context) -> dict:
    """スケジュールを開始する。"""
    _set_schedules(cfg, enabled=True, dry_run=dry_run, best_effort=False)
    return {}


@lambda_handler("scheduler-check", SchedulerCheckConfig)
def check(cfg: SchedulerCheckConfig, event: dict, *, dry_run: bool,
          context) -> dict:
    """グループが利用できる状態か、スケジュールが開始されているかを確認する。"""
    scheduler = client("scheduler", cfg.region)

    # aws scheduler get-schedule-group --name <g> の State
    # DELETING は削除処理中で、そのグループのスケジュールは動かない。
    group = scheduler.get_schedule_group(Name=cfg.schedule_group)
    if group["State"] != GROUP_ACTIVE:
        raise NotRecoverableError(json.dumps(
            {"scheduler": {cfg.schedule_group: {"group_state": group["State"]}}},
            ensure_ascii=False, default=str))

    # aws scheduler list-schedules --group-name <g> の Schedules[].State
    paginator = scheduler.get_paginator("list_schedules")
    not_enabled = [s["Name"]
                   for page in paginator.paginate(GroupName=cfg.schedule_group)
                   for s in page["Schedules"]
                   if s.get("State") != STATE_ENABLED]

    return {"not_enabled": not_enabled} if not_enabled else {}
