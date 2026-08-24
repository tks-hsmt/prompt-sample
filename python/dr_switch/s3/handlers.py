"""S3 レプリケーションの停止 / 開始 / 確認.

必要な IAM（自関数が対象とするリージョンのバケットのみ）:
    s3:GetReplicationConfiguration / s3:PutReplicationConfiguration
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
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from botocore.exceptions import ClientError

from dr_switch.core import (
    NotRecoverableError,
    client,
    lambda_handler,
    run_per_item,
)
from dr_switch.s3.config import (
    S3BaseConfig,
    S3BlockConfig,
    S3CheckConfig,
    S3EnableConfig,
)

if TYPE_CHECKING:
    from mypy_boto3_s3.literals import ReplicationRuleStatusType

NOT_CONFIGURED = "ReplicationConfigurationNotFoundError"

# 値は boto3-stubs の ReplicationRuleStatusType に対応（Enabled / Disabled の 2 値）。
RULE_ENABLED: ReplicationRuleStatusType = "Enabled"
RULE_DISABLED: ReplicationRuleStatusType = "Disabled"

# レプリケーションの滞留を見るメトリクス。
# 待ち系 3 つ（Latency / BytesPending / OperationsPending）はいずれも
# **宛先バケットのリージョン**に発行されるため、切替先から自リージョンの
# CloudWatch を見れば済む。クロスリージョンアクセスは発生しない。
#
# OperationsFailedReplication だけは送信元リージョンに発行されるため、
# 切替先からは見えない。ここでは確認しない。
PENDING_METRIC = "OperationsPendingReplication"
S3_NAMESPACE = "AWS/S3"
METRIC_PERIOD_SEC = 60


def _set_replication(cfg: S3BaseConfig, bucket: str, *,
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


def _apply(cfg: S3BaseConfig, *, enabled: bool, dry_run: bool,
           best_effort: bool) -> None:
    run_per_item(
        cfg.replication_buckets,
        lambda bucket: _set_replication(
            cfg, bucket, enabled=enabled, dry_run=dry_run),
        best_effort=best_effort, what="s3-replication",
    )


@lambda_handler("s3-block", S3BlockConfig, best_effort=True)
def block(cfg: S3BlockConfig, event: dict, *, dry_run: bool, context) -> dict:
    """レプリケーションを停止する。"""
    _apply(cfg, enabled=False, dry_run=dry_run, best_effort=True)
    return {}


@lambda_handler("s3-enable", S3EnableConfig)
def enable(cfg: S3EnableConfig, event: dict, *, dry_run: bool, context) -> dict:
    """逆方向レプリケーションを開始する.

    トラフィックを受け始める前に実行すること。ライブレプリケーションの
    対象は Enabled 後に書かれたオブジェクトだけのため。
    """
    _apply(cfg, enabled=True, dry_run=dry_run, best_effort=False)
    return {}


def _pending_replication(cw, bucket: str, rule_id: str,
                         lookback: int) -> float | None:
    """レプリケーション待ちの操作数を返す。データが無ければ None.

    aws cloudwatch get-metric-statistics --namespace AWS/S3
      --metric-name OperationsPendingReplication
      --dimensions Name=DestinationBucket,Value=<bucket> Name=RuleId,Value=<id>
      --statistics Maximum --period 60 --start-time <t0> --end-time <t1>
      の Datapoints[].Maximum

    メトリクスはベストエフォート配信で、公式に「完全性と適時性は保証され
    ない」と明記されている。データが無いことを「待ちなし」と解釈すると
    見逃すため、None を返して呼び出し側で区別する。
    """
    now = datetime.now(UTC)
    points = cw.get_metric_statistics(
        Namespace=S3_NAMESPACE,
        MetricName=PENDING_METRIC,
        Dimensions=[
            {"Name": "DestinationBucket", "Value": bucket},
            {"Name": "RuleId", "Value": rule_id},
        ],
        StartTime=now - timedelta(seconds=lookback),
        EndTime=now,
        Period=METRIC_PERIOD_SEC,
        Statistics=["Maximum"],
    )["Datapoints"]
    if not points:
        return None
    # 最新のデータポイントを見る
    return max(points, key=lambda p: p["Timestamp"])["Maximum"]


@lambda_handler("s3-check", S3CheckConfig)
def check(cfg: S3CheckConfig, event: dict, *, dry_run: bool, context) -> dict:
    """レプリケーションルールの Status と、滞留の有無を確認する.

    バケットの存在確認は行わない。バケットには状態という概念が無く、
    時間経過で失われる性質のものでもないため、切替時に確認する意味がない。
    """
    s3 = client("s3", cfg.region)
    cw = client("cloudwatch", cfg.region)
    problems: dict[str, dict] = {}
    fatal: dict[str, dict] = {}

    for bucket in cfg.replication_buckets:
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
            continue

        # レプリケーション待ちが残っていないか。閉塞の後に確認すること。
        # 送信元への書き込みが続いていれば待ちは減らない。
        pending = {
            rule["ID"]: value
            for rule in rules
            if (value := _pending_replication(
                cw, bucket, rule["ID"], cfg.replication_lookback)) is not None
            and value > 0
        }
        if pending:
            problems[bucket] = {"operations_pending_replication": pending}

    if fatal:
        raise NotRecoverableError(
            json.dumps({"s3": fatal}, ensure_ascii=False, default=str))
    return problems
