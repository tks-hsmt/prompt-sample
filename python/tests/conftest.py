"""moto を使うテストの共通設定.

AWS 公式ブログ（Unit Testing AWS Lambda with Python and Mock AWS Services）が
推奨する方式に従い、moto で AWS サービスをシミュレートする。自前の Fake
クラスと違い、API 呼び出しの引数が不正なら moto がエラーを返すため、
「呼び出し方が正しいか」まで検証できる。

moto が再現しない応答フィールドは、テストごとにバックエンドへ注入する。
"""

from __future__ import annotations

import pytest

from dr_switch.core.aws import client

REGION = "ap-northeast-1"
PEER_REGION = "ap-northeast-3"
ACCOUNT_ID = "123456789012"


@pytest.fixture(autouse=True)
def _aws_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """実際のクラウドリソースへ誤ってアクセスしないためのダミー認証情報.

    AWS 公式ブログでも推奨されている。認証情報が解決されないまま moto を
    使うと、環境によっては実 API を叩きうる。
    """
    for key, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SECURITY_TOKEN": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": REGION,
    }.items():
        monkeypatch.setenv(key, value)


@pytest.fixture(autouse=True)
def _clear_client_cache():
    """core.client の functools.cache をテストごとに捨てる.

    moto のモックはテストごとに張り直されるため、前のテストで作った
    クライアントを使い回すと別のバックエンドを見てしまう。
    """
    client.cache_clear()
    yield
    client.cache_clear()


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    """環境変数を設定するヘルパ。config の from_env を通すために使う。"""

    def _set(**kwargs: str) -> None:
        monkeypatch.setenv("REGION", REGION)
        for key, value in kwargs.items():
            monkeypatch.setenv(key, value)

    return _set


class Context:
    """Lambda のコンテキストの代用。ハンドラは中身を使わない。"""

    function_name = "test"
    invoked_function_arn = f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:test"
    aws_request_id = "test-request-id"
