"""dr-scheduler: EventBridge Scheduler スケジュールの停止 / 開始.

イベント駆動は EventBridge Rules ではなく Scheduler を使用しているため、
`events` ではなく `scheduler` クライアントを叩く。

===========================================================================
必要な IAM 権限
---------------------------------------------------------------------------
    scheduler:ListSchedules
        arn:aws:scheduler:<両リージョン>:<acct>:schedule-group/<自チームグループ>
    scheduler:GetSchedule / scheduler:UpdateSchedule
        arn:aws:scheduler:<両リージョン>:<acct>:schedule/<自チームグループ>/*
    iam:PassRole
        各スケジュールの実行ロール ARN

    ※ iam:PassRole が必須。UpdateSchedule が Target.RoleArn を含む全
      パラメータを要求するため、実行ロールを渡す権限がないと失敗する。
      他のどの Lambda にも不要な権限なので見落としやすく、dry_run の
      定期実行で早期に検証すること。
    ※ Resource は自チーム専用グループに限定する。default グループには
      他チームのスケジュールが同居しているため、権限としても対象外にする。
===========================================================================

入力 : {"role": "self"|"peer", "enabled": true|false, "dry_run": false}
出力 : {"action": "scheduler", "changed": [...], "skipped": [...], ...}
"""

from __future__ import annotations

from common import RegionConfig, client, get_logger, ops_handler, run_per_item

logger = get_logger(__name__)

# get_schedule が返すもののうち、update_schedule に渡せない読み取り専用フィールド
SCHEDULE_READONLY_KEYS = frozenset({
    "ResponseMetadata", "Arn", "CreationDate", "LastModificationDate",
})


def _set_state(scheduler, cfg: RegionConfig, name: str, state: str) -> dict:
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
    return {"state": state}


@ops_handler("scheduler")
def handler(cfg: RegionConfig, event: dict, *, dry_run: bool, context) -> dict:
    """自チーム専用グループのスケジュールを一括で有効化 / 無効化する.

    スケジュール名をハードコードせず list_schedules で列挙するため、
    スケジュール追加時に切替コードの更新が漏れる事故が起きない。
    """
    enabled = bool(event["enabled"])
    scheduler = client("scheduler", cfg.region)
    want = "ENABLED" if enabled else "DISABLED"

    # 一覧取得の失敗は 1 件の失敗ではないので、@ops_handler に分類させる
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

    # 1 件失敗しても残りは必ず試みる。閉塞では止められた分だけリスクが減る。
    changed = run_per_item(targets, apply, role=cfg.role, what="scheduler")

    return {"enabled": enabled, "group": cfg.schedule_group,
            "changed": changed, "skipped": skipped}
