# 自己レビュー結果

全ファイルを通しで検査した結果。19 件。

---

## 重大（DR 切替を失敗させる / 事故を起こす）

### F-01 一時的なネットワークエラーが「恒久エラー」に分類される  **【解消】**

**TRANSIENT_ERRORS（botocore の ConnectionError / HTTPClientError）を無条件に RetryableError とし、RETRYABLE_CODES に SlowDown 等を追加した。** 以下は変更前の記録。


`common.py` `raise_classified()`

`RETRYABLE_CODES` は `ClientError` のエラーコードしか見ていない。
`BotoCoreError` のサブクラス（`ConnectTimeoutError`、`ReadTimeoutError`、
`EndpointConnectionError`）は `code = ""` となり、**リトライ対象にならない**。

結果、`role=self` の操作中に一瞬の接続タイムアウトが起きると、元の例外が
そのまま送出され **切替ワークフローが停止する**。本来は再試行すべき場面。

あわせて、S3 のスロットリングは `ThrottlingException` ではなく `SlowDown` を
返すため、`s3_replication` のスロットリングも恒久エラー扱いになる。

対処案: `BotoCoreError` 系のタイムアウト・接続エラーを無条件に
`RetryableError` とし、`RETRYABLE_CODES` に `SlowDown`、`RequestTimeout`、
`RequestTimeoutException`、`ProvisionedThroughputExceededException` を追加する。

### F-02 API Gateway のリソースポリシーを全置換している  **【解消】**

**閉塞方式をステージのスロットリング 0 に変更したため、リソースポリシーを
一切触らなくなった。以下は変更前の記録。**


`apigw.py` `_build_policy()`

目標状態のポリシーをゼロから組み立てて `replace` している。これは
**DR 用の Lambda がリソースポリシー全体を所有している場合にのみ安全**。

既存ポリシーに IP 制限や VPC エンドポイント制限など他の Statement があると、
**閉塞のたびにそれらを消し去る**。開放時にも復元されない。

Terraform でリソースポリシーを管理している場合はドリフトも発生する。

対処案: 既存 Statement を保持し、`Sid == DRFenceDenyAll` の追加・削除だけを
行う。ただし「中間状態を引きずらない」という当初の意図とはトレードオフに
なるため、現状のポリシー内容を確認したうえで方針を決める必要がある。

### F-03 ポリシーのパース失敗時に既存設定を上書きする  **【解消】**

**F-02 と同じ理由で解消。以下は変更前の記録。**


`apigw.py` `_parse_policy()`

パースに失敗すると `{}` を返す。呼び出し側は `already = False` と判断し、
`blocked=True` なら**そのまま全置換に進む**。F-02 と重なると、パース不能な
ポリシーを持つ API のポリシーが黙って消える。

対処案: パース失敗は例外にする（ワークフロー停止）。

---

## 中（動作不良・運用上の問題）

### F-04 構造化ログの `extra` が機能していない  **【解消】**

**LogRecord の標準属性との差分を取る方式に変更し、logger.info(..., extra={...}) が実際に JSON へ出るようにした。** 以下は変更前の記録。


`common.py` `_JsonFormatter.format()`

`getattr(record, "extra", None)` は常に `None`。`logger.info(msg, extra={...})`
は `record.extra` を作らず、`record.<キー名>` を直接生やすため。
実行して確認済み。この分岐は永久に実行されない。

### F-05 `HOME` が上書きされない  **【解消】**

**os.environ["HOME"] = "/tmp" で無条件に上書き。ベースイメージ側の設定に依存しなくなった。** 以下は変更前の記録。


`check_workload.py` `_build_clients()`

`os.environ.setdefault("HOME", "/tmp")` は既に `HOME` が設定されていれば
何もしない。Lambda のコンテナイメージで `HOME=/root` 等が設定されていると、
AWS CLI が書き込み不可のパスにキャッシュを作ろうとして失敗する。

対処案: `os.environ["HOME"] = "/tmp"` で無条件に上書きする。

### F-06 kubeconfig の書き込みがアトミックでない  **【解消】**

**毎回生成する方式に変更。exists() 判定を廃止したため、不完全なファイルが残る経路自体が消えた。** 以下は変更前の記録。


`check_workload.py` `_build_clients()`

`update-kubeconfig` がタイムアウト等で中断すると、不完全なファイルが
`/tmp/kubeconfig` に残る。次のウォーム起動では `Path(...).exists()` が
`True` を返すため再生成されず、**そのコンテナが生きている間ずっと壊れ続ける**。

対処案: 一時ファイルに書いてから `os.replace()` でアトミックに差し替える。

### F-07 Kubernetes API 呼び出しにタイムアウトが無い  **【解消】**

**全呼び出しに _request_timeout=(3, 10) を指定。** 以下は変更前の記録。


`check_workload.py`

`list_node()` / `list_namespaced_deployment()` / `list_namespaced_pod()` に
タイムアウト指定が無い。クラスタ API が応答しない場合、Lambda のタイムアウト
まで待つことになる。DR 切替中に無駄な時間を消費する。

対処案: `_request_timeout=(3, 10)` 等を指定する。

### F-08 botocore の内部リトライと Step Functions の Retry が二重になる  **【解消】**

**BOTO_CONFIG で connect 3 / read 5 秒、max_attempts=2 を明示。API 呼び出し 1 回の最悪待ち時間が 16 秒に有界化された。** 以下は変更前の記録。


全ファイル

`boto3.client()` を素で作っているため、botocore のデフォルトリトライが効く。
そのうえで Step Functions 側でも Retry するため、待ち時間が掛け算になる。
どちらがどれだけ待つかが設計上把握できていない。

対処案: `Config(retries={"mode": "standard", "max_attempts": N})` を明示し、
Step Functions 側の Retry 設定と合わせて総待ち時間を設計する。

### F-09 ページネーションの欠落  **【解消】**

**check_lambda / check_alarms ともページネータに変更。** 以下は変更前の記録。


- `check_lambda.py` `list_event_source_mappings()` — 既定 100 件で打ち切り
- `check_alarms.py` `describe_alarms()` — 既定 100 件で打ち切り

いずれも件数が少なければ問題ないが、無言で切り捨てられる点が危険。
`scheduler_ops` と `s3_replication` はページネータを使っており不統一。

---

## 低（設計・保守性）

### F-10 Dockerfile が全関数に AWS CLI を含めている

必要なのは `check_workload` のみ。残り 9 本のイメージサイズと
コールドスタートに影響する（AWS CLI v2 は約 200MB）。

対処案: イメージを 2 つに分けるか、コールドスタート実測後に判断する。

### F-11 boto3 のバージョンが固定されていない

`requirements.txt`

ランタイム同梱の boto3 を使う前提だが、コンテナイメージなら固定できる。
DR 切替という失敗が許されない用途で、AWS 側の更新による挙動変化を
受け入れている状態。

### F-12 単一アカウント前提が暗黙になっている  **【解消】**

**同一アカウントであることを確認。前提として README と apigw.py に明記した。** 以下は変更前の記録。


`apigw.py`

`context.invoked_function_arn` からアカウント ID を取り出し、PEER 側の
ARN 組み立てにも使っている。クロスアカウント構成では破綻する。
前提として明記されていない。

### F-13 `create_deployment` の蓄積  **【解消】**

**スロットリング方式に変更し create_deployment を使わなくなったため解消。** 以下は変更前の記録。


`apigw.py`

切替のたびに新しいデプロイメントを作成する。API あたりのデプロイメント数には
上限があるため、長期運用で頭打ちになる可能性がある。未確認。

### F-14 `run_per_item` の入れ子 try/except が読みにくい  **【解消】**

**分類のみを行う classify() を分離し、送出は呼び出し側で行う形にした。入れ子が解消。** 以下は変更前の記録。


`common.py`

`raise_classified` を呼んで即座に捕まえ直す構造になっている。分類と送出が
同じ関数に同居しているのが原因。

対処案: 分類だけを行う `classify(exc, role) -> Exception` を分け、
送出は呼び出し側で行う。

### F-15 センチネル値をデータと混ぜている  **【解消】**

**「1 台も無い」と「Ready でない台がある」を別の理由として返す形に変更。** 以下は変更前の記録。


`check_workload.py` `_not_ready_nodes()`

Hybrid Node が 0 件のとき `["<no hybrid node found>"]` を返す。
ノード名のリストに文字列センチネルを混ぜており、型として不正確。

### F-16 ライブラリのログが混在する  **【解消】**

**JSON フォーマッタをルートロガーに設定。botocore 等のログも JSON になる。** 以下は変更前の記録。


`common.py` `get_logger()`

自前ロガーは JSON で出るが、botocore / urllib3 / kubernetes のログは
ルートロガー経由でプレーンテキストのまま出る。ログ形式が混在する。

### F-17 `role` の値を検証していない  **【指摘を取り下げ】**

**指摘として不適切だったため撤回し、実装も戻した。**

理由: 呼び出し元は Step Functions に確定しており、外部 API から任意の値が
渡る経路ではない。自分たちが書く ASL のタイポを実行時 IF で守るのは、
Python にもLambda にもそのような慣習が無い上、この 1 箇所だけに入れるのは
一貫性を欠く。防げるのはエラーメッセージの読みやすさだけで、dry_run の
初回実行で露見するため本番に潜伏するリスクも無い。

以下は変更前の記録。


`common.py` `ops_handler()`

`event["role"]` に `"peers"` のようなタイポがあると、
`PEERS_REGION が無い` という分かりにくい `KeyError` になる。

### F-18 `common.py` が 5 つの責務を持つ  **【解消】**

**config / errors / aws / logging_json / handlers の 5 ファイルに分割。** 以下は変更前の記録。


設定・例外・ログ・デコレータ・集約ヘルパが同居。320 行。

### F-19 ユニットテストが無い

デコレータと `run_per_item` はアドホックに実行確認しただけで、
テストコードとして残っていない。

---

## 制御設計として再検討すべき点（コードの不具合ではない）

### D-01 「未収束」を例外で表現している

AWS が示すポーリングの定型は `Wait` + `Choice`（job-poller パターン）で、
`Retry` は本来一時的な**エラー**のための機構。「まだ準備できていない」は
正常な過程であってエラーではないため、意味論の混同という批判が成り立つ。

ASL の簡潔さとのトレードオフであり、優劣ではない。

### D-02 閉塞失敗時に無条件で続行している  **【現状維持と決定】**

**閉塞が失敗する主要因は旧リージョンの障害そのもので、その場合は旧側の
サービスも動いていない。残る「部分障害で閉塞だけ失敗」のケースは判定手段が
無いため対処しない。詳細は README を参照。** 以下は指摘時の記録。


「閉塞に失敗した」と「旧リージョンが停止している」は別物。旧リージョンが
生きていて閉塞だけ失敗した場合、**両リージョンが同時にアクティブになる**。

本来は「閉塞成功」または「旧リージョン停止の積極的な証拠」のどちらかを
条件にすべきだが、後者を確認していない。

### D-03 正常性確認が実機能を検証していない

API GW の 1 リクエストを除き、確認しているのはリソースの状態のみ。
アプリケーションが実際に処理できるかを検証していない。

### D-04 ワークフロー全体のタイムアウトと二重実行防止が未設計

Step Functions 側の話だが、Lambda 側で冪等性を担保している前提が
明文化されていない。


---

## 対応状況（2 巡目時点）

- **重大 3 件**: すべて解消（F-01 / F-02 / F-03）
- **中 6 件**: すべて解消（F-04 〜 F-09）
- **低 10 件**: F-14 / F-15 / F-16 / F-17 / F-18 を解消。
  F-17 は指摘そのものを取り下げ。残りは F-10（Dockerfile の分割）、
  F-11（boto3 のバージョン固定）、F-19（ユニットテスト未作成）。
  F-12・F-13 は前提確認により解消
- **制御設計 D-01 〜 D-04**: すべて判断済み。D-01 / D-02 / D-03 は現状維持
  （理由は README に記録）、D-04 は ASL 着手時の要件とする
