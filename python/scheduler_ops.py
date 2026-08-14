"""dr-scheduler: EventBridge Scheduler スケジュールの停止 / 開始.

Rules ではなく Scheduler を使うため、events ではなく scheduler
クライアントを叩く。

必要な IAM:
    scheduler:ListSchedules / GetSchedule / UpdateSchedule
    iam:PassRole  … UpdateSchedule が Target.RoleArn を要求するため必須

入力 : {"role": "self"|"peer", "enabled": bool, "dry_run": bool}
出力 : {"action": "scheduler", "changed": [...], "skipped": [...]}
"""

from __future__ import annotations

from aws import client
from config import SchedulerConfig
from handlers import ops_handler, run_per_item
from logging_json import get_logger

logger = get_logger(__name__)

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


@ops_handler("scheduler", SchedulerConfig)
def handler(cfg: SchedulerConfig, event: dict, *, dry_run: bool, context) -> dict:
    """グループ内のスケジュールを一括で有効化 / 無効化する。"""
    enabled = bool(event["enabled"])
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

    changed = run_per_item(targets, apply, role=cfg.role, what="scheduler")

    return {"enabled": enabled, "group": cfg.schedule_group,
            "changed": changed, "skipped": skipped}
