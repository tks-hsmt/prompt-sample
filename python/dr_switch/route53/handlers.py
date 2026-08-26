"""カスタムドメインの向き先を切り替える.

API Gateway をカスタムドメイン方式にしたことで、切替は Route 53 の
Alias レコードの向き先を変える操作になる。レコードは 1 つで、
AliasTarget.DNSName を切替先リージョンの VPC エンドポイントへ向ける。

**これは閉塞ではない。** DNS を切り替えても、キャッシュを持つリゾルバは
しばらく旧リージョンへ送り続ける。旧リージョンを止めるのは
apigateway の block（スロットリング 0）が担当する。

Alias レコードは自分で TTL を持たず、ターゲット側の値を使う。

必要な IAM:
    switch  route53:ListResourceRecordSets / route53:ChangeResourceRecordSets
            （対象ホストゾーン）
    check   route53:ListResourceRecordSets（対象ホストゾーン）

ハンドラ（成功時は何も返さない。失敗・未収束は例外で表現する）:
    switch  向き先を切り替える。入力 {"dry_run": bool}
    check   向き先が切り替わっているか確認。入力 {"dry_run": bool}
"""

from __future__ import annotations

import copy
import json
import logging

from dr_switch.core import NotRecoverableError, client, lambda_handler
from dr_switch.route53.config import Route53CheckConfig, Route53SwitchConfig

logger = logging.getLogger(__name__)

RECORD_TYPE = "A"

# Route 53 はグローバルサービスで、API エンドポイントは us-east-1 の 1 つだけ
#（公式に「北京・寧夏以外のリージョンでは us-east-1 を指定する」と明記）。
# 東京・大阪どちらから呼んでも同じホストゾーンを操作できる。
ROUTE53_REGION = "us-east-1"


def _normalize(name: str) -> str:
    """レコード名を末尾ドット付きに揃える.

    Route 53 の応答は常に末尾ドット付き。設定値は付いていないことがある。
    """
    return name if name.endswith(".") else f"{name}."


def _current_record(r53, cfg) -> dict | None:
    """対象のレコードセット全体を返す。無ければ None.

    aws route53 list-resource-record-sets --hosted-zone-id <id>
      --start-record-name <name> --start-record-type A --max-items 1
      の ResourceRecordSets[0]

    StartRecordName / StartRecordType で対象から探し始めるので、
    ゾーンに多数のレコードがあっても 1 ページで足りる。
    """
    wanted = _normalize(cfg.record_name)
    response = r53.list_resource_record_sets(
        HostedZoneId=cfg.hosted_zone_id,
        StartRecordName=wanted,
        StartRecordType=RECORD_TYPE,
        MaxItems="1",
    )
    for record in response["ResourceRecordSets"]:
        if record["Name"] == wanted and record["Type"] == RECORD_TYPE:
            return record
    return None


def _same_target(record: dict, dns_name: str) -> bool:
    """現在の向き先が指定と一致するか。末尾ドットと大文字小文字を無視する。"""
    current = record.get("AliasTarget", {}).get("DNSName", "")
    return current.rstrip(".").lower() == dns_name.rstrip(".").lower()


def _missing_record_error(cfg) -> NotRecoverableError:
    return NotRecoverableError(json.dumps(
        {"route53": {_normalize(cfg.record_name): {
            "reason": "record does not exist"}}},
        ensure_ascii=False))


@lambda_handler("route53-switch", Route53SwitchConfig)
def switch(cfg: Route53SwitchConfig, event: dict, *, dry_run: bool,
           context) -> dict:
    """Alias レコードの向き先を切替先の VPC エンドポイントへ変える.

    **読み取ったレコードセットをそのまま使い、AliasTarget の DNSName と
    HostedZoneId だけを差し替える。** UPSERT はレコードセット全体を置き換える
    ため、こちらで組み立て直すと EvaluateTargetHealth やルーティングポリシー
    （Weight / Failover / HealthCheckId など）を意図せず上書きしてしまう。

    レコードが無い状態は設定漏れで、待っても現れない。UPSERT は作成もできて
    しまうので、事前に弾く。

    伝播（GetChange が INSYNC になること）は待たない。待つと Lambda の
    タイムアウトに縛られるため、収束は check が確認する。
    """
    r53 = client("route53", ROUTE53_REGION)
    record = _current_record(r53, cfg)

    if record is None:
        raise _missing_record_error(cfg)

    if _same_target(record, cfg.alias_dns_name):
        logger.info("route53: already pointing at %s", cfg.alias_dns_name)
        return {}

    if dry_run:
        logger.info("route53: would point %s to %s (current: %s)",
                    record["Name"], cfg.alias_dns_name,
                    record["AliasTarget"]["DNSName"])
        return {}

    # 向き先だけを差し替える。他のフィールドは読み取ったまま渡す。
    updated = copy.deepcopy(record)
    updated["AliasTarget"]["DNSName"] = cfg.alias_dns_name
    updated["AliasTarget"]["HostedZoneId"] = cfg.alias_hosted_zone_id

    # aws route53 change-resource-record-sets --hosted-zone-id <id>
    #   --change-batch '{"Changes": [{"Action": "UPSERT", ...}]}'
    #   の ChangeInfo.Id
    #
    # ChangeAction は CREATE / DELETE / UPSERT の 3 つだけで、既存レコードの
    # 値を変える手段は UPSERT のみ（API モデルで確認済み）。
    response = r53.change_resource_record_sets(
        HostedZoneId=cfg.hosted_zone_id,
        ChangeBatch={
            "Comment": "DR switch",
            "Changes": [{"Action": "UPSERT", "ResourceRecordSet": updated}],
        },
    )
    logger.info("route53: %s -> %s (change=%s)",
                record["Name"], cfg.alias_dns_name,
                response["ChangeInfo"]["Id"])
    return {}


@lambda_handler("route53-check", Route53CheckConfig)
def check(cfg: Route53CheckConfig, event: dict, *, dry_run: bool,
          context) -> dict:
    """レコードが切替先を向いているか確認する.

    Route 53 のレコードは change_resource_record_sets の直後から
    list_resource_record_sets に反映される。反映されていない状態は
    伝播待ちなので RetryableError。
    """
    r53 = client("route53", ROUTE53_REGION)
    record = _current_record(r53, cfg)

    if record is None:
        raise _missing_record_error(cfg)

    if not _same_target(record, cfg.alias_dns_name):
        return {"alias_dns_name": record["AliasTarget"]["DNSName"],
                "expected": cfg.alias_dns_name}
    return {}
