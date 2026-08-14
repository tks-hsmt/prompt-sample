# DR 切替 Lambda 実装メモ

## エラー処理の契約

Step Functions が区別する必要があるのは 2 つだけ。

| 例外 | 意味 | ASL 側 |
|---|---|---|
| `RetryableError` | 一時的。または「まだ収束していない」 | `Retry` |
| `ContinuableError` | 失敗したが作業継続してよい（旧 ACTIVE 側の閉塞失敗） | `Catch` |
| （型を定義しない） | それ以外すべて | 何にもマッチせず**ワークフロー停止** |

「止めるべきエラー」に独自の型は定義しない。`Retry` にも `Catch` にも
マッチしない例外は Step Functions が失敗させるため、停止はデフォルトの
挙動である。設定不備や権限不足はバグであり、未捕捉例外として止まるのが
正しい。`ConfigError` / `FatalError` / `PermanentFailure` のような型は作らない。

`raise_classified()` の振り分け:

| role | エラー | 結果 |
|---|---|---|
| any | スロットリング等 | `RetryableError` |
| peer | その他の AWS エラー | `ContinuableError` |
| self | その他の AWS エラー | 元の例外をそのまま送出（停止） |

AWS SDK 以外の例外（`KeyError` 等）は分類せず素通しさせる。自分のコードの
バグをインフラ障害に化けさせないため。

### 捕捉はデコレータに集約する

AWS 例外の `try/except` は `@ops_handler` の中だけに置き、個々の操作側では
書かない。

- 分類の判断材料はエラーコードと role の 2 つで、どちらもデコレータが
  持っている。個々の操作側で捕捉しても情報を足せず catch-and-rethrow になる
- 操作系を追加した人が `try/except` を書き忘れると、PEER 側の恒久エラーが
  `ContinuableError` にならずワークフローを止める。集約すればこの失敗モード
  自体が消える

### 複数インスタンスのループは `run_per_item` に統一

操作系の Lambda は「リソース種別」を担当し、その中の個別インスタンス
（バケット、スケジュール）はループで処理する。`common.run_per_item()` が
その集約を担う。

- **1 件失敗しても残りを必ず試みる。** 最初の失敗で中断すると、止められた
  はずの残りが開いたままになる。閉塞では止められた分だけリスクが減るため、
  部分的な成功に価値がある
- 一時エラーが 1 つでも混ざれば `RetryableError`（操作は冪等なので全体
  再試行で問題ない）、恒久エラーのみなら `ContinuableError`
- `role=self` の恒久エラーは `raise_classified` が元の例外をそのまま送出
  するため、内側の `except` に捕まらず即座に停止する
- 自分のコードのバグ（`KeyError` 等）は分類せず素通し

`scheduler_ops` と `s3_replication` は同じ性質の操作なので、同じヘルパを使う。
一覧取得（`list_schedules`）の失敗は 1 件の失敗ではないので、ループの外に
置いて `@ops_handler` に分類させる。

観測系の `check_*` は揃えない。AWS エラーが出るのは権限不足やリソース不在＝
バグで、続けても意味がないため中断が妥当。「未収束」の問題はループが正常に
回りきってから全件まとめて送出するので、集約は既に効いている。

## 横断処理はデコレータ

`common.py` の 2 つのデコレータが、role 解決・設定読み込み・ログ・応答整形・
例外送出を担う。各ハンドラは自分の確認内容だけを書く。

### 観測系 `@check_handler(name)`

```python
@check_handler("nlb")
def handler(cfg: RegionConfig) -> dict:
    return problems   # 問題のある項目だけを返す。正常なら {}
```

- **正常時は何も返さない**（`None`）
- 問題があれば、その項目だけを JSON にして `RetryableError` で送出
- 項目ごとの `ok` フラグは持たない。例外に載る = NG が自明なので冗長
- AWS API のエラーは握りつぶさず素通し。権限不足やリソース不在はバグであり、
  待っても直らないので止まるのが正しい

### 操作系 `@ops_handler(action)`

```python
@ops_handler("apigw")
def handler(cfg: RegionConfig, event: dict, *, dry_run: bool, context) -> dict:
    return {"changed": True, ...}
```

`{"action", "role", "region", "dry_run"}` を付けて返す。

## 構成

Lambda は**操作するリソース単位**で分割する。各ファイルの docstring 冒頭に
必要な IAM 権限を明記している。

| # | 関数 | ファイル | 対象リソース | 種別 | 対象リージョン |
|---|---|---|---|---|---|
| 1 | dr-apigw | `apigw.py` | API Gateway | 変更 | 引数（self/peer） |
| 2 | dr-scheduler | `scheduler_ops.py` | EventBridge Scheduler | 変更 | 引数（self/peer） |
| 3 | dr-s3-replication | `s3_replication.py` | S3 レプリケーション | 変更 | 引数（self/peer） |
| 4 | dr-check-apigw | `check_apigw.py` | API Gateway | 観測 | SELF |
| 5 | dr-check-lambda | `check_lambda.py` | Lambda | 観測 | SELF |
| 6 | dr-check-dynamodb | `check_dynamodb.py` | DynamoDB | 観測 | SELF |
| 7 | dr-check-nlb | `check_nlb.py` | NLB | 観測 | SELF |
| 8 | dr-check-s3 | `check_s3.py` | S3 | 観測 | SELF |
| 9 | dr-check-alarms | `check_alarms.py` | CloudWatch | 観測 | SELF |
| 10 | dr-check-workload | `check_workload.py` | EKS Pod / Hybrid Node | 観測 | SELF |

`dr-s3-replication` は **S3 案 A を採用する場合のみ**デプロイする（後述）。

10 本とも東京・大阪の**両リージョンにデプロイ**する。実行するのは常に
これから ACTIVE になる側。切替方向は「どのリージョンの Step Functions を
叩いたか」で決まるため、入力に direction を持たない。

作らないもの:

- SQS ドレイン確認 … 障害時は待っても解消しないため実施しない
- スケールアップ … 両リージョン同レプリカ数のため不要

### 共通モジュール

| ファイル | 責務 |
|---|---|
| `config.py` | リソース単位の設定クラスと環境変数の読み込み |
| `errors.py` | 例外定義、`classify()` / `raise_classified()` |
| `aws.py` | `BOTO_CONFIG`（タイムアウト・リトライ）と `client()` |
| `logging_json.py` | JSON フォーマッタとロガー設定 |
| `handlers.py` | `ops_handler` / `check_handler` / `run_per_item` |

`classify()` は分類結果を**返す**（送出しない）。`run_per_item` が
「分類はしたいが今は送出したくない」ため、入れ子の try/except を避けられる。
単に送出したい場合は `raise_classified()` を使う。

### 設定クラスはリソース単位

Lambda をリソース単位に分割しているので、設定クラスも同じ単位で分ける。
`BaseConfig`（role + region）を基底に、各リソース用のクラスが必要な項目だけを持つ。

| クラス | 固有フィールド | 使う Lambda |
|---|---|---|
| `BaseConfig` | （role, region のみ） | — |
| `ApiGatewayConfig` | rest_api_id, stage, throttle_rate, throttle_burst, health_url | dr-apigw, dr-check-apigw |
| `SchedulerConfig` | schedule_group | dr-scheduler |
| `S3Config` | replication_buckets | dr-s3-replication, dr-check-s3 |
| `LambdaConfig` | function_names | dr-check-lambda |
| `DynamoDbConfig` | table_names | dr-check-dynamodb |
| `NlbConfig` | target_group_arns | dr-check-nlb |
| `AlarmConfig` | alarm_prefix | dr-check-alarms |
| `EksConfig` | cluster_name, namespaces, hybrid_node_selector | dr-check-workload |

生成は `<Cls>.from_env(role)`。デコレータに設定クラスを渡す。

```python
@check_handler("nlb", NlbConfig)
def handler(cfg: NlbConfig) -> dict:
    ...
```

**必須項目を必須として宣言できる**のが最大の利点。単一の設定クラスを全 Lambda で
共有していたときは、ある Lambda に必須の項目でも他には不要なのですべて省略可能に
せざるを得ず、設定漏れを検出できなかった（`REST_API_ID` が空文字のまま API を
叩いて分かりにくいエラーになる）。分割後は `from_env` の時点で
`environment variable not set: SELF_REST_API_ID` で止まる。

必須は `REGION` に加えて、`REST_API_ID` / `STAGE`（ApiGatewayConfig）、
`SCHEDULE_GROUP`（SchedulerConfig）、`EKS_CLUSTER_NAME`（EksConfig）。

## デプロイ（コンテナイメージ）

既存の Lambda に合わせてコンテナイメージでデプロイする。Layer は使わない。
10 本で同一イメージを共有し、ハンドラだけ変える。

```hcl
resource "aws_lambda_function" "check_nlb" {
  package_type = "Image"
  image_uri    = "${aws_ecr_repository.dr.repository_url}:${var.image_tag}"
  image_config {
    command = ["check_nlb.handler"]
  }
  # ...
}
```

`check_workload` のみ VPC 設定が必要（既存の Pod 再起動 Lambda と同じ
サブネット・セキュリティグループ）。イメージには AWS CLI と
`kubernetes` パッケージを同梱している。

ログは `logging_json.py` の JSON フォーマッタで構造化する。ランタイムのログ形式
設定にも Powertools にも依存しない。

**ルートロガーに設定している**ため、botocore / urllib3 / kubernetes など
ライブラリのログも同じ JSON 形式で出る。CloudWatch Logs Insights で JSON
フィールドを条件にクエリしたときに、ライブラリのログ行だけパースできない
という事態を避けるため。ライブラリのログレベルは既定で `WARNING`
（`LIBRARY_LOG_LEVEL`）、アプリは `INFO`（`LOG_LEVEL`）。

`logger.info("msg", extra={"bucket": "b1"})` の独自フィールドも JSON に出る。

## IAM（リソース単位）

観測系（4〜10）はすべて読み取り専用ロールにできる。変更系（1〜3）とは
必ずロールを分けること。

| 関数 | 必要なアクション | Resource |
|---|---|---|
| dr-apigw | `apigateway:GET` `apigateway:PATCH` | **両リージョン**の `/restapis/<id>/stages/<stage>` |

東京・大阪は同一 AWS アカウント。両リージョンのリソースを同じ実行ロールで
操作できることを前提にしている。

| dr-scheduler | `scheduler:ListSchedules` `GetSchedule` `UpdateSchedule` `iam:PassRole` | **両リージョン**の自チームグループのみ／スケジュール実行ロール |
| dr-s3-replication | `s3:GetReplicationConfiguration` `PutReplicationConfiguration` `iam:PassRole` | **両リージョン**のバケット／レプリケーションロール |
| dr-check-apigw | `apigateway:GET` | SELF の `/restapis/<id>/stages/<stage>` |
| dr-check-lambda | `lambda:GetFunction` `ListEventSourceMappings` | SELF の対象関数／ESM は `*` |
| dr-check-dynamodb | `dynamodb:DescribeTable` | SELF の対象テーブル |
| dr-check-nlb | `elasticloadbalancing:DescribeTargetHealth` | `*` |
| dr-check-s3 | `s3:ListBucket` `GetReplicationConfiguration` | SELF のバケット |
| dr-check-alarms | `cloudwatch:DescribeAlarms` | `*` |
| dr-check-workload | `eks:DescribeCluster` `sts:GetCallerIdentity` | SELF のクラスタ／`*` |

注意点:

- `dr-scheduler` の `iam:PassRole` は必須。`UpdateSchedule` が
  `Target.RoleArn` を含む全パラメータを要求するため、これがないと失敗する。
  他のどの Lambda にも不要な権限なので見落としやすい
- `dr-scheduler` の Resource は自チーム専用グループに限定する。default
  グループには他チームのスケジュールが同居しているため、権限としても外す
- `dr-check-workload` の Pod / Node 参照権限は IAM ではなく Kubernetes RBAC
  側（EKS アクセスエントリで view 相当にマッピング）
- S3 は SSE-S3（AES256）で SSE-C 禁止のため、KMS 関連の権限は全関数で不要

## 環境変数

東京デプロイと大阪デプロイで self / peer を入れ替えて同じモジュールを呼ぶ。
関数ごとに必要なものだけ渡してよい。

```hcl
environment {
  variables = {
    SELF_REGION              = "ap-northeast-3"
    SELF_REST_API_ID         = var.self_rest_api_id         # ApiGatewayConfig で必須
    SELF_STAGE               = var.self_stage               # ApiGatewayConfig で必須
    SELF_HEALTH_URL          = var.self_health_url
    SELF_SCHEDULE_GROUP      = var.self_schedule_group      # SchedulerConfig で必須
    SELF_FUNCTION_NAMES      = jsonencode(var.self_function_names)
    SELF_TABLE_NAMES         = jsonencode(var.self_table_names)
    SELF_TARGET_GROUP_ARNS   = jsonencode(var.self_target_group_arns)
    SELF_ALARM_PREFIX        = var.self_alarm_prefix
    SELF_EKS_CLUSTER_NAME    = var.self_eks_cluster_name    # EksConfig で必須
    SELF_EKS_NAMESPACES      = jsonencode(var.self_eks_namespaces)
    SELF_REPLICATION_BUCKETS = jsonencode(var.self_replication_buckets) # 案 A のみ

    PEER_REGION              = "ap-northeast-1"
    PEER_REST_API_ID         = var.peer_rest_api_id
    PEER_STAGE               = var.peer_stage
    PEER_SCHEDULE_GROUP      = var.peer_schedule_group
    PEER_REPLICATION_BUCKETS = jsonencode(var.peer_replication_buckets) # 案 A のみ
  }
}
```

## Step Functions への組み込み

```json
"FenceApiGw": {
  "Type": "Task",
  "Resource": "arn:aws:states:::lambda:invoke",
  "Parameters": {
    "FunctionName": "dr-apigw",
    "Payload": {"role": "peer", "blocked": true, "dry_run.$": "$.dry_run"}
  },
  "Retry": [{
    "ErrorEquals": ["RetryableError", "Lambda.ServiceException",
                    "Lambda.TooManyRequestsException"],
    "IntervalSeconds": 5, "MaxAttempts": 3, "BackoffRate": 2
  }],
  "Catch": [{
    "ErrorEquals": ["ContinuableError"],
    "ResultPath": "$.fenceApiGwError",
    "Next": "FenceScheduler"
  }],
  "Next": "FenceScheduler"
}
```

観測系は `Retry` の間隔を長くするだけでよい。**`Wait` + `Choice` の待機
ループは不要**。`MaxAttempts` がそのまま待機上限になる。

```json
"CheckNlb": {
  "Type": "Task",
  "Resource": "arn:aws:states:::lambda:invoke",
  "Parameters": {"FunctionName": "dr-check-nlb"},
  "Retry": [{
    "ErrorEquals": ["RetryableError"],
    "IntervalSeconds": 30, "BackoffRate": 1.0, "MaxAttempts": 10
  }],
  "End": true
}
```

- 同じ例外名でも、ステートごとに間隔と回数を別々に指定できる
- 閉塞（role=peer）の失敗は `ResultPath` に記録して続行。リソース単位に
  分かれているので、どれが閉塞できなかったかが実行履歴からそのまま分かる
- 観測系 7 本は `Parallel` で並列実行する。どれか 1 つでも
  `RetryableError` で失敗すれば Parallel 全体が失敗する

## ループを Lambda 内で回す理由（Map を使わない）

Step Functions の Map で 1 バケット / 1 スケジュールずつ呼び分ける案は採らない。

- **Inline Map** は部分失敗を許容できない（`ToleratedFailureCount` /
  `ToleratedFailurePercentage` は Distributed Map の機能）。1 件失敗した時点で
  Map 全体が失敗するため、現在の「残りを試みて集約」が再現できず改悪になる
- **Distributed Map** なら `ToleratedFailurePercentage: 100` で同じ挙動を宣言
  でき、失敗した項目だけの redrive も使える。ただし子ワークフロー実行が項目数
  ぶん発生し、ResultWriter を使うなら両リージョンに S3 バケットが必要で、
  項目リストの置き場所が環境変数から ASL 側へ分散する
- 対象がバケット数個・スケジュール数個という規模では構成が重すぎる。得られる
  のは実質 redrive だけで、操作が冪等な今回はワークフロー再実行で代替できる

## フェーズ順序

```
Fence(peer): apigw -> scheduler          # ContinuableError を Catch して続行
  [案 A のみ] s3-replication(self, enabled=true)
  [案 A のみ] s3-replication(peer,  enabled=false)   # 失敗許容
Check(self): apigw / lambda / dynamodb / nlb / s3 / alarms / workload  # 並列
Activate(self): scheduler -> apigw       # 失敗は未捕捉 = 停止
```

案 A の `role=self` 有効化は **必ず Activate より前**。ライブレプリケーション
の対象は「ルールが Enabled になった後に書かれたオブジェクト」だけなので、
開放が先だと取りこぼしが発生し、Batch Replication での追い付きが必要になる。

## API Gateway の閉塞方式

**ステージのスロットリングを 0 にする方式**を採る。

    閉塞: rateLimit=0 / burstLimit=0  -> 全リクエストが 429
    開放: 環境変数（または引数）の値に戻す

復元値は `SELF_THROTTLE_RATE` / `SELF_THROTTLE_BURST`（既定 10000 / 5000）。
Step Functions から `{"throttle": {"rate": ..., "burst": ...}}` で上書きできる。

### リソースポリシー Deny 方式を採らない理由

1. リソースポリシーの更新は再デプロイしないと反映されず 2 手になる
2. `/policy` への patch は `op:replace` のみ（`op:add` / `op:remove` は
   非サポート）で、Statement 単位の更新ができない。既存ポリシーに IP 制限等が
   あると閉塞のたびに壊す危険がある
3. 旧アクティブ側の閉塞はリージョン障害中に実行できない可能性があり、構造的に
   ベストエフォート。遮断機構だけを「保証された」ものにする必然性がない

スロットリングは公式に「ベストエフォートで適用され、保証された上限ではなく
目標値」とされている。理論上わずかな漏れの可能性は残るが、3 の理由から許容する。

### 前提と副作用

現在ステージには明示的なスロットリング設定が無く、`get-stage` に出ている
10000 / 5000 は**アカウントのデフォルト値**（10,000 RPS / バースト 5,000）が
表示されているだけ。

- スロットリング設定は `op:remove` が非サポートのため、一度書き込むと
  「未設定」には戻せない。ただし復元先がデフォルトと同値なので実害はない
- **明示設定後は、アカウントのクォータを引き上げてもこのステージは環境変数の
  値のままになる。** 引き上げ時はここも上げること
- この副作用は「明示設定が存在すること」から生じるもので、Terraform で
  管理するかどうかとは無関係。Lambda が復元時に書き込む以上、どちらにしても
  発生する

### Terraform で管理しない理由

`aws_api_gateway_method_settings` で管理することもできるが、Lambda が値を
書き換えるためドリフト対策（`ignore_changes`）が必要になる。上記の副作用は
Terraform 管理の有無で変わらないため、管理コストが増えるだけで得るものがない。
復元値は Lambda の環境変数だけで持つ。

## S3 レプリケーション: 案 A / 案 B

未確定のため両方に対応できる形にしてある。

### 案 A（切替時に Status をトグル）

平時は逆方向ルールを `Disabled` にしておき、切替時に `dr-s3-replication`
で Status を書き換える。

Terraform との整合: 現行モジュールは `var.run_replication` で `status` を
制御しているため、Lambda が書き換えるとドリフトする。次のいずれかが必要。

- `lifecycle { ignore_changes = [rule] }` を付けて Status を Terraform 管理外にする
- 切替を恒久化する際に tfvars の `run_replication` も合わせて更新する運用にする

案 A 固有のリスク: `PutBucketReplication` は宛先バケットの存在を検証する。
相手リージョンが全域障害の最中にこの検証が通るかは公式に明記がなく確定
できない。切替のクリティカルパスにこの不確実性を抱える点が弱点。

### 案 B（双方向を常時 Enabled）

`dr-s3-replication` はデプロイしない。切替時の S3 操作はゼロになる。
tfvars で両リージョンとも `run_replication = true` に固定する。
`dr-check-s3` は「意図せず Disabled になっていないか」の確認として機能する。

### 両案共通

`aws_s3_bucket_replication_configuration` の rule に `metrics` を有効化して
おくこと。切替可否のゲートには使わないが、切替後の突合と平時の RPO 可視化に
必要。東京 -> 大阪ルールの PENDING は宛先である大阪の CloudWatch に出るため、
東京障害中でも大阪側から取り残し量を読める。

`delete_marker_replication` は `Disabled` のまま。仕様上オブジェクト削除が
ないため `Enabled` にする利点がなく、誤削除が両リージョンへ波及するリスク
だけが残る。誤削除時に切替先へコピーが残ることが保護になる。

## EventBridge Scheduler

イベント駆動は EventBridge **Rules ではなく Scheduler**（スケジュール）を
使っている。`events` ではなく `scheduler` クライアントを叩く。

自チーム専用のスケジュールグループが独立して存在するため、
`SCHEDULE_GROUP` にそのグループ名を指定すればグループ内全件が対象になる。
default グループの他チーム分には触れない。

### UpdateSchedule の注意点

State だけを渡す API は存在しない。`UpdateSchedule` は必須パラメータを
すべて要求し、渡した内容でスケジュールを丸ごと置き換える。指定しなかった
パラメータは null になる。そのため必ず

    get_schedule -> 読み取り専用フィールドを除去 -> State を差し替え -> update_schedule

の順で行う。S3 の `put_bucket_replication` と同じ構造。
除去する読み取り専用フィールドは
`ResponseMetadata` / `Arn` / `CreationDate` / `LastModificationDate`。

冪等判定は `list_schedules` の戻り値に含まれる `State` で行うため、
変更不要なものに `get_schedule` は発行しない。

## NLB の構成と判定の意味

NLB とターゲットグループは AWS Load Balancer Controller が Service から作成。
**ターゲットタイプは IP**、トラフィック・ヘルスチェックとも **TCP** で、
`HealthCheckPort` は `traffic-port`。ターゲットグループは 2 つ（Port 1 / 9116）。

IP モードでは NLB が Pod IP へ直接トラフィックを送るため、トラフィックは
kube-proxy を経由せず、`externalTrafficPolicy` は判定に関係しない。
Controller は Endpoints / EndpointSlices からターゲットを解決し、一覧に無い
ターゲットは即座に登録解除する。したがって

    登録されているターゲット ≒ Ready な Pod

`dr-check-nlb` は「登録済みのターゲットがすべて健全か」だけを見る。

    unhealthy == 0  かつ  initial == 0  かつ  healthy >= 1

必要数を満たしているかの判定は `dr-check-workload` に一本化している。
`initial` を許容しないのは、EndpointSlice の更新が ELB のターゲット登録より
速く進むため、早すぎる開放を防ぐ必要があるから。

Hybrid Node の Ready 状態や Pending 状態の Pod はターゲットグループに
現れないため、`dr-check-workload` との併用が前提。

## EKS ワークロードの判定

`dr-check-workload` は `EKS_NAMESPACES` の各 namespace の Deployment を
列挙し、`status.ready_replicas >= spec.replicas` で判定する。

- 必要数は Deployment 自身が持っているので設定値として与えない
- Deployment 名も列挙するため、設定は namespace のリストだけで済む
- `status.replicas`（作成済み数）ではなく `ready_replicas` を見る

検出できないもの: 「本来 3 のはずが `spec.replicas` が 1 になっている」ような
平時の構成ドリフト。切替の瞬間に気づいても打つ手がないので、dry_run の
定期実行や Terraform のドリフト検知で拾う。

## check_workload の接続方式

既存の Pod 再起動 Lambda と同じ方式（`aws eks update-kubeconfig`）を使う。

- CA 証明書とトークン取得は CLI が肩代わりするため、Python 側の実装は不要
  （kubeconfig の exec プラグインが `aws eks get-token` を都度実行する）
- クラスタ API エンドポイントはプライベートのみのため、到達可能な
  VPC・サブネット・セキュリティグループに配置する（既存 Lambda と同じ設定）
- 実行ロールを EKS アクセスエントリで view 相当にマッピングする

## タイムアウト（外部通信すべてに設定）

応答しない相手を待ち続けて RTO を消費しないよう、外部と通信するすべての
呼び出しにタイムアウトを設定している。

| 呼び出し | 設定 | 場所 |
|---|---|---|
| AWS API（boto3） | connect 3 秒 / read 5 秒、botocore リトライ 1 回（合計 2 試行） | `common.BOTO_CONFIG` |
| Kubernetes API | connect 3 秒 / read 10 秒 | `check_workload.K8S_TIMEOUT` |
| `aws eks update-kubeconfig` | 15 秒 | `check_workload.UPDATE_KUBECONFIG_TIMEOUT_SEC` |
| ヘルスチェックの HTTPS | 5 秒 | `check_apigw.HEALTH_TIMEOUT_SEC` |

boto3 の既定は connect / read とも 60 秒で、DR 切替には長すぎる。
`BOTO_CONFIG` を `common.client()` に必ず適用しているため、素の
`boto3.client()` を直接呼ばないこと。

botocore 内部のリトライは最小限（`max_attempts=1`）にし、再試行は
Step Functions の `Retry` に任せる。実行履歴に残り、待機時間を宣言で
制御できるため。なお `max_attempts` は**リトライ回数**であって総試行回数
ではない（1 なら初回 + リトライ 1 回 = 合計 2 回）。API 呼び出し 1 回の
最悪待ち時間は `(3 + 5) * 2 = 16 秒`。

Lambda 自体のタイムアウトは 60 秒。いずれの関数も待機ループを持たないので、
これ以上長くすると応答しない相手を待つだけになる。

## dry_run

変更系 3 本は `{"dry_run": true}` で読み取りと「実行予定の操作」の返却のみ
行う。EventBridge Scheduler で週次実行すれば、IAM 権限不足や設定漏れを平時に
検出できる（訓練時にしか動かないコードの潜伏対策）。特に `dr-scheduler` の
`iam:PassRole` は見落としやすいので、ここで早期に検証する。

## 制御設計についての判断

| 論点 | 判断 |
|---|---|
| 「未収束」を例外（`RetryableError`）で表現する | **現状維持**。AWS のポーリング定型は `Wait` + `Choice` であり意味論の批判は成立するが、実務上の差はなく ASL が単純になる利点が上回る |
| 閉塞失敗時に無条件で続行する | **現状維持**（下記） |
| 正常性確認が実機能を検証していない | **制約として受容**。NE 機器への誤警報になるため真のエンドツーエンド試験ができない。切替後の流量メトリクスの立ち上がりで代替する |
| ワークフロー全体のタイムアウト・二重実行防止 | Step Functions 側の作業。ASL 着手時の要件とする |

### 閉塞失敗時の扱い（現状維持と決定）

閉塞に失敗しても切替を続行する。理由は、閉塞が失敗する主要因が旧リージョンの
障害そのものであり、その場合は旧リージョン側のサービスも動いていないため。

残るのは「部分障害で旧リージョンのアプリは生きているが、閉塞だけ失敗した」
ケースで、理論上は両リージョンが同時にアクティブになりうる。ただし
**判定手段がない**ため、対処を入れないと決めた。

判定手段がない根拠:

- 新 ACTIVE 側から旧リージョンを 1 回叩く方式は単一拠点からの判定になり、
  リージョン間のネットワーク分断を「旧リージョンの停止」と誤判定する。
  Route 53 が 18% という合議しきい値を持つのは、まさにこの誤判定
  （ネットワーク条件による一部拠点からの隔離）を避けるため
- 多拠点合議で判定するなら Route 53 ヘルスチェックを新設し、CloudWatch
  （us-east-1）の `HealthCheckStatus` を読む必要がある。DR 専用のリソース
  追加は避ける方針のため採らない
- ARC のルーティングコントロールは「人間やランブックをフェイルオーバーの
  ループに入れたい場合の正解」とされる明示的なスイッチであり、AWS 自身も
  自動推論ではなく人間の判断を前提にしている

閉塞失敗は `ContinuableError` として実行履歴の `ResultPath` に残るため、
事後に「どのリソースが閉塞できなかったか」は追跡できる。

## 残っている作業

| 項目 | 内容 |
|---|---|
| F-10 | Dockerfile の分割。AWS CLI が必要なのは `check_workload` のみだが、10 本すべてのイメージに入っている |
| F-11 | boto3 のバージョン固定。現在はランタイム同梱を使っている |
| F-19 | ユニットテスト未作成 |
| — | Step Functions の ASL 本体（フェーズ構成、Parallel、Retry / Catch の配線、全体タイムアウト、二重実行防止） |
| — | Terraform 側の関数定義（`image_config.command` でハンドラを切り替える 10 本分） |
| — | S3 レプリケーションの案 A / 案 B の決定 |
