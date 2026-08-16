"""EventBridge Scheduler スケジュールの停止 / 開始.

イベント駆動は Rules ではなく Scheduler を使うため、events ではなく
scheduler クライアントを叩く。

必要な IAM（自関数が対象とするリージョンのグループのみ）:
    scheduler:ListSchedules / GetSchedule / UpdateSchedule
    iam:PassRole  … UpdateSchedule が Target.RoleArn を要求するため必須

ハンドラ:
    block   スケジュールを停止。入力 {"dry_run": bool}
    enable  スケジュールを開始。入力 {"dry_run": bool}
"""

from __future__ import annotations

from dr_switch.core import client, ops_handler, run_per_item
from dr_switch.scheduler.config import SchedulerConfig

# get_schedule が返すもののうち、update_schedule に渡せない読み取り専用フィールド
SCHEDULE_READONLY_KEYS = frozenset({
    "ResponseMetadata", "Arn", "CreationDate", "LastModificationDate",
})


def _set_state(scheduler, cfg: SchedulerConfig, name: str, state: str) -> dict:
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


def _set_schedules(cfg: SchedulerConfig, *, enabled: bool, dry_run: bool,
                   best_effort: bool) -> dict:
    scheduler = client("scheduler", cfg.region)
    want = "ENABLED" if enabled else "DISABLED"

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

    changed = run_per_item(targets, apply, best_effort=best_effort,
                           what="scheduler")

    return {"group": cfg.schedule_group, "changed": changed, "skipped": skipped}


@ops_handler("scheduler-block", SchedulerConfig, best_effort=True)
def block(cfg: SchedulerConfig, event: dict, *, dry_run: bool, context) -> dict:
    """スケジュールを停止する。"""
    return _set_schedules(cfg, enabled=False, dry_run=dry_run, best_effort=True)


@ops_handler("scheduler-enable", SchedulerConfig, best_effort=False)
def enable(cfg: SchedulerConfig, event: dict, *, dry_run: bool, context) -> dict:
    """スケジュールを開始する。"""
    return _set_schedules(cfg, enabled=True, dry_run=dry_run, best_effort=False)
