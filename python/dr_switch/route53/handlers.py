"""カスタムドメインの向き先を切り替える.

API Gateway をカスタムドメイン方式にしたことで、切替は Route 53 の
Alias レコードの向き先を変える操作になる。レコードは 1 つで、
AliasTarget.DNSName を切替先リージョンの VPC エンドポイントへ向ける。

**これは閉塞ではない。** DNS を切り替えても、キャッシュを持つリゾルバは
しばらく旧リージョンへ送り続ける。旧リージョンを止めるのは
apigateway の block（スロットリング 0）が担当する。

Alias レコードは自分で TTL を持たず、ターゲット側の値を使う。

必要な IAM:
    switch  route53:ChangeResourceRecordSets（対象ホストゾーン）
            route53:GetChange（"*"。リソースレベル権限に非対応）
    check   route53:ListResourceRecordSets（対象ホストゾーン）

ハンドラ（成功時は何も返さない。失敗・未収束は例外で表現する）:
    switch  向き先を切り替える。入力 {"dry_run": bool}
    check   向き先が切り替わっているか確認。入力 {"dry_run": bool}
"""

from __future__ import annotations

import json
import logging

from dr_switch.core import NotRecoverableError, client, lambda_handler
from dr_switch.route53.config import Route53CheckConfig, Route53SwitchConfig

logger = logging.getLogger(__name__)

RECORD_TYPE = "A"

# Alias レコードのヘルスチェック評価。現在の設定を維持する。
EVALUATE_TARGET_HEALTH = True

# Route 53 はグローバルサービスで、エンドポイントも 1 つしかない。
# クライアント生成時のリージョン指定は認証に使われるだけで、
# 東京・大阪どちらから呼んでも同じホストゾーンを操作できる。
ROUTE53_REGION = "us-east-1"


def _normalize(name: str) -> str:
    """レコード名を末尾ドット付きに揃える.

    Route 53 の応答は常に末尾ドット付き。設定値は付いていないことがある。
    """
    return name if name.endswith(".") else f"{name}."


def _current_alias(r53, cfg) -> dict | None:
    """対象レコードの現在の AliasTarget を返す。無ければ None.

    aws route53 list-resource-record-sets --hosted-zone-id <id>
      --query "ResourceRecordSets[?Name=='<name>' && Type=='A']"
      の AliasTarget

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
            return record.get("AliasTarget")
    return None


@lambda_handler("route53-switch", Route53SwitchConfig)
def switch(cfg: Route53SwitchConfig, event: dict, *, dry_run: bool,
           context) -> dict:
    """Alias レコードの向き先を切替先の VPC エンドポイントへ変える.

    UPSERT なのでレコードが無ければ作られる。ただし本来は存在するはずで、
    無い状態は設定漏れなので check 側で検出する。

    伝播（GetChange が INSYNC になること）は待たない。待つと Lambda の
    タイムアウトに縛られるため、収束は check が確認する。
    """
    r53 = client("route53", ROUTE53_REGION)
    wanted = _normalize(cfg.record_name)
    current = _current_alias(r53, cfg)

    if current and current["DNSName"].rstrip(".").lower() == \
            cfg.alias_dns_name.rstrip(".").lower():
        logger.info("route53: already pointing at %s", cfg.alias_dns_name)
        return {}

    if dry_run:
        logger.info("route53: would point %s to %s (current: %s)",
                    wanted, cfg.alias_dns_name,
                    current["DNSName"] if current else "none")
        return {}

    # aws route53 change-resource-record-sets --hosted-zone-id <id>
    #   --change-batch '{"Changes": [{"Action": "UPSERT", ...}]}'
    #   の ChangeInfo.Id
    response = r53.change_resource_record_sets(
        HostedZoneId=cfg.hosted_zone_id,
        ChangeBatch={
            "Comment": "DR switch",
            "Changes": [{
                "Action": "UPSERT",
                "ResourceRecordSet": {
                    "Name": wanted,
                    "Type": RECORD_TYPE,
                    "AliasTarget": {
                        "HostedZoneId": cfg.alias_hosted_zone_id,
                        "DNSName": cfg.alias_dns_name,
                        "EvaluateTargetHealth": EVALUATE_TARGET_HEALTH,
                    },
                },
            }],
        },
    )
    logger.info("route53: %s -> %s (change=%s)",
                wanted, cfg.alias_dns_name, response["ChangeInfo"]["Id"])
    return {}


@lambda_handler("route53-check", Route53CheckConfig)
def check(cfg: Route53CheckConfig, event: dict, *, dry_run: bool,
          context) -> dict:
    """レコードが切替先を向いているか確認する.

    Route 53 のレコードは change_resource_record_sets の直後から
    list_resource_record_sets に反映される。反映されていない状態は
    伝播待ちなので RetryableError。

    レコードそのものが存在しない場合は設定漏れで、待っても現れない。
    """
    r53 = client("route53", ROUTE53_REGION)
    current = _current_alias(r53, cfg)

    if current is None:
        raise NotRecoverableError(json.dumps(
            {"route53": {_normalize(cfg.record_name): {
                "reason": "record does not exist"}}},
            ensure_ascii=False))

    actual = current["DNSName"].rstrip(".").lower()
    expected = cfg.alias_dns_name.rstrip(".").lower()
    if actual != expected:
        return {"alias_dns_name": current["DNSName"],
                "expected": cfg.alias_dns_name}
    return {}
