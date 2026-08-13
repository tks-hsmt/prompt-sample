"""dr-scheduler: EventBridge Scheduler スケジュールの停止 / 開始.

イベント駆動は EventBridge Rules ではなく Scheduler を使用しているため、
`events` ではなく `scheduler` クライアントを叩く。

===========================================================================
必要な IAM 権限（この Lambda のみ）
---------------------------------------------------------------------------
    scheduler:ListSchedules
        arn:aws:scheduler:<両リージョン>:<acct>:schedule-group/<group>
    scheduler:GetSchedule / scheduler:UpdateSchedule
        arn:aws:scheduler:<両リージョン>:<acct>:schedule/<group>/*
    iam:PassRole              各スケジュールの実行ロール ARN

    ※ iam:PassRole が必須。UpdateSchedule が Target.RoleArn を含む全
      パラメータを要求するため、実行ロールを渡す権限がないと失敗する。
      見落としやすいので dry_run の定期実行で早期に検証すること。
    ※ 自チーム専用のスケジュールグループのみを Resource に指定する。
      default グループには他チームのスケジュールが同居しているため、
      権限としても対象外にしておく。
===========================================================================

入力:
    {"role": "self" | "peer", "enabled": true|false, "dry_run": false}

出力:
    {"action": "scheduler", "role": "...", "target_region": "...",
     "changed": [...], "skipped": [...]}
"""

from __future__ import annotations

import logging

from common import AWS_ERRORS, RegionConfig, Role, client, config, raise_classified

logger = logging.getLogger(__name__)

# get_schedule が返すもののうち、update_schedule に渡せない読み取り専用フィールド
SCHEDULE_READONLY_KEYS = frozenset({
    "ResponseMetadata", "Arn", "CreationDate", "LastModificationDate",
})


def _set_schedule_state(scheduler, cfg: RegionConfig, name: str,
                        state: str) -> None:
    """1 件のスケジュールの State を変更する.

    State だけを渡す API は存在しない。UpdateSchedule は必須パラメータを
    すべて要求し、渡した内容でスケジュールを丸ごと置き換える。指定しな
    かったパラメータは null になるため、必ず
    get_schedule -> 読み取り専用フィールド除去 -> State 差し替え -> update
    の順で行う。State だけ渡すとターゲットもスケジュール式も消える。
    """
    current = scheduler.get_schedule(Name=name, GroupName=cfg.schedule_group)
    params = {key: value for key, value in current.items()
              if key not in SCHEDULE_READONLY_KEYS}
    params["State"] = state
    scheduler.update_schedule(**params)


def set_schedules(cfg: RegionConfig, *, enabled: bool, dry_run: bool) -> dict:
    """対象グループのスケジュールを一括で有効化 / 無効化する.

    自チーム専用グループを指定する前提のため、グループ内の全件が対象。
    スケジュール名をハードコードしないので、追加時の更新漏れが起きない。
    """
    scheduler = client("scheduler", cfg.region)
    want = "ENABLED" if enabled else "DISABLED"
    changed: list[str] = []
    skipped: list[str] = []

    list_kwargs: dict = {"GroupName": cfg.schedule_group}
    if cfg.schedule_name_prefix:
        list_kwargs["NamePrefix"] = cfg.schedule_name_prefix

    try:
        paginator = scheduler.get_paginator("list_schedules")
        for page in paginator.paginate(**list_kwargs):
            for summary in page["Schedules"]:
                name = summary["Name"]
                # 一覧に State が含まれるので、冪等判定に get_schedule は不要
                if summary.get("State") == want:
                    skipped.append(name)
                    continue
                if not dry_run:
                    _set_schedule_state(scheduler, cfg, name, want)
                changed.append(name)
    except AWS_ERRORS as exc:
        raise_classified(exc, role=cfg.role,
                         what=f"scheduler({cfg.role}:{cfg.schedule_group})")

    logger.info("scheduler %s: group=%s enabled=%s changed=%d skipped=%d",
                cfg.region, cfg.schedule_group, enabled,
                len(changed), len(skipped))
    return {"ok": True, "enabled": enabled, "changed": changed,
            "skipped": skipped, "dry_run": dry_run}


def handler(event: dict, context) -> dict:
    role: Role = event["role"]
    enabled = bool(event["enabled"])
    dry_run = bool(event.get("dry_run", False))
    cfg = config(role)

    logger.info("scheduler start: role=%s region=%s enabled=%s dry_run=%s",
                role, cfg.region, enabled, dry_run)

    return {
        "action": "scheduler",
        "role": role,
        "target_region": cfg.region,
        **set_schedules(cfg, enabled=enabled, dry_run=dry_run),
    }
