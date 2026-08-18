"""boto3 クライアントの生成."""

from __future__ import annotations

from functools import cache

import boto3
from botocore.config import Config

# タイムアウトは既定の 60 秒では長すぎるため明示する。
# read_timeout=10 は、呼ぶのが describe / update 系のコントロールプレーン API で
# 通常 0.3 秒程度のため 30 倍の余裕を取った値。短くしすぎると成功するはずの
# 呼び出しが打ち切られて 3 回リトライされ、かえって遅くなる。
# 最悪待ち時間は接続不能で connect*3 = 15 秒、ハングで (5+10)*3 = 45 秒 / 呼び出し。
#
# リトライは standard モードの既定（合計 3 回）をそのまま使う。boto3 の既定は
# まだ legacy で、AWS は legacy を非推奨としているためモードのみ明示する。
# 既定を変えない理由は、バックオフが短く（一過性エラーで合計約 75ms、
# スロットリングで約 1.5 秒）RTO への影響が無視できる一方、回数を削ると
# 本来 SDK が吸収できる失敗が呼び出し元まで漏れるため。
#
# 注意: max_attempts は設定場所で意味が変わる。
#   Config(retries={"max_attempts": N})  -> リトライ回数（合計 N+1 回）
#   環境変数 AWS_MAX_ATTEMPTS            -> 合計試行回数（1 でリトライ無効）
BOTO_CONFIG = Config(
    connect_timeout=5,
    read_timeout=10,
    retries={"mode": "standard"},
)


@cache
def client(service: str, region: str, config: Config = BOTO_CONFIG):
    """リージョンを明示してクライアントを返す（結果はキャッシュする）.

    素の boto3.client() を直接呼ぶと BOTO_CONFIG が効かないため、
    必ずこの関数を使うこと。呼び出し先の実行時間が長いなど、既定と違う
    タイムアウトが要る場合だけ config を渡す。

    Config は同一性でハッシュされるため、モジュールレベルの定数を渡すこと。
    呼び出しのたびに Config(...) を生成すると、キャッシュが増え続ける。
    """
    return boto3.client(service, region_name=region, config=config)
