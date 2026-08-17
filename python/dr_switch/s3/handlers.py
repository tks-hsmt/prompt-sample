"""S3 レプリケーションの停止 / 開始 / 確認.

必要な IAM（自関数が対象とするリージョンのバケットのみ）:
    s3:GetReplicationConfiguration / s3:PutReplicationConfiguration
    s3:ListBucket … check の head_bucket に必要
    iam:PassRole  … レプリケーション用ロール

バケットは SSE-S3（AES256）で SSE-C 禁止のため KMS 権限は不要。

PutBucketReplication は宛先バケットの存在を検証する。宛先リージョンが
利用不能なときにこの検証が通るかは公式に明記がない。

ハンドラ（成功時は何も返さない。失敗・未収束は例外で表現する）:
    block   レプリケーションを停止。入力 {"dry_run": bool}
    enable  逆方向レプリケーションを開始。入力 {"dry_run": bool}
    check   バケットの到達性と Status を確認。入力 {}
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from botocore.exceptions import ClientError

from dr_switch.core import (
    NotRecoverableError,
    client,
    lambda_handler,
    run_per_item,
)
from dr_switch.s3.config import S3Config

if TYPE_CHECKING:
    from mypy_boto3_s3.literals import ReplicationRuleStatusType

NOT_CONFIGURED = "ReplicationConfigurationNotFoundError"

# 値は boto3-stubs の ReplicationRuleStatusType に対応（Enabled / Disabled の 2 値）。
RULE_ENABLED: ReplicationRuleStatusType = "Enabled"
RULE_DISABLED: ReplicationRuleStatusType = "Disabled"


def _set_replication(cfg: S3Config, bucket: str, *,
                     enabled: bool, dry_run: bool) -> dict:
    # run_per_item が結果を集約するため dict を返す（ハンドラの戻り値ではない）
    """レプリケーションルールの Status を一括で切り替える.

    put_bucket_replication は設定を丸ごと置き換えるため、
    get -> 修正 -> put の順で行う。
    """
    s3 = client("s3", cfg.region)
    want = RULE_ENABLED if enabled else RULE_DISABLED

    # aws s3api get-bucket-replication / put-bucket-replication --bucket <b>
    configuration = s3.get_bucket_replication(
        Bucket=bucket)["ReplicationConfiguration"]
    current = {rule["ID"]: rule["Status"] for rule in configuration["Rules"]}

    if all(status == want for status in current.values()):
        return {"changed": False, "status": want, "rules": current}

    if dry_run:
        return {"changed": False, "status": want, "rules": current,
                "would": f"set all rules to {want}"}

    for rule in configuration["Rules"]:
        rule["Status"] = want
    s3.put_bucket_replication(
        Bucket=bucket, ReplicationConfiguration=configuration)

    return {"changed": True, "status": want,
            "rules": {rule["ID"]: want for rule in configuration["Rules"]}}


def _apply(cfg: S3Config, *, enabled: bool, dry_run: bool,
           best_effort: bool) -> None:
    run_per_item(
        cfg.replication_buckets,
        lambda bucket: _set_replication(
            cfg, bucket, enabled=enabled, dry_run=dry_run),
        best_effort=best_effort, what="s3-replication",
    )


@lambda_handler("s3-replication-block", S3Config, best_effort=True)
def block(cfg: S3Config, event: dict, *, dry_run: bool, context) -> dict:
    """レプリケーションを停止する。"""
    _apply(cfg, enabled=False, dry_run=dry_run, best_effort=True)
    return {}


@lambda_handler("s3-replication-enable", S3Config)
def enable(cfg: S3Config, event: dict, *, dry_run: bool, context) -> dict:
    """逆方向レプリケーションを開始する.

    トラフィックを受け始める前に実行すること。ライブレプリケーションの
    対象は Enabled 後に書かれたオブジェクトだけのため。
    """
    _apply(cfg, enabled=True, dry_run=dry_run, best_effort=False)
    return {}


@lambda_handler("s3-check", S3Config)
def check(cfg: S3Config, event: dict, *, dry_run: bool, context) -> dict:
    """バケットの到達性とレプリケーション Status を確認する。"""
    s3 = client("s3", cfg.region)
    problems: dict[str, dict] = {}
    fatal: dict[str, dict] = {}

    for bucket in cfg.replication_buckets:
        # aws s3api head-bucket --bucket <b>（アクセス不可なら例外を素通しさせる）
        s3.head_bucket(Bucket=bucket)

        # aws s3api get-bucket-replication --bucket <b>
        #   の ReplicationConfiguration.Rules[].Status
        try:
            rules = s3.get_bucket_replication(
                Bucket=bucket)["ReplicationConfiguration"]["Rules"]
        except ClientError as exc:
            if exc.response["Error"]["Code"] != NOT_CONFIGURED:
                raise
            # 設定そのものが無い状態は待っても現れない
            fatal[bucket] = {"reason": "replication configuration does not exist"}
            continue

        disabled = {rule["ID"]: rule["Status"] for rule in rules
                    if rule["Status"] != RULE_ENABLED}
        if disabled:
            problems[bucket] = {"rules_not_enabled": disabled}

    if fatal:
        raise NotRecoverableError(
            json.dumps({"s3": fatal}, ensure_ascii=False, default=str))
    return problems
