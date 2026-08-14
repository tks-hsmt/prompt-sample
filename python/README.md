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

ログは `common.py` の JSON フォーマッタで構造化する。ランタイムのログ形式
設定にも Powertools にも依存しない。

## IAM（リソース単位）

観測系（4〜10）はすべて読み取り専用ロールにできる。変更系（1〜3）とは
必ずロールを分けること。

| 関数 | 必要なアクション | Resource |
|---|---|---|
| dr-apigw | `apigateway:GET` `PATCH` `POST` `UpdateRestApiPolicy` | **両リージョン**の `/restapis/<id>` と配下 |
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
    SELF_REST_API_ID         = var.self_rest_api_id
    SELF_STAGE               = var.self_stage
    SELF_HEALTH_URL          = var.self_health_url
    SELF_SCHEDULE_GROUP      = var.self_schedule_group   # 自チーム専用グループ
    SELF_FUNCTION_NAMES      = jsonencode(var.self_function_names)
    SELF_TABLE_NAMES         = jsonencode(var.self_table_names)
    SELF_TARGET_GROUP_ARNS   = jsonencode(var.self_target_group_arns)
    SELF_ALARM_PREFIX        = var.self_alarm_prefix
    SELF_EKS_CLUSTER_NAME    = var.self_eks_cluster_name
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

## タイムアウト

いずれも待機しない設計なので 30〜60 秒で十分。
長いタイムアウトは、API が応答しない状態で無駄に待つだけになる。

## dry_run

変更系 3 本は `{"dry_run": true}` で読み取りと「実行予定の操作」の返却のみ
行う。EventBridge Scheduler で週次実行すれば、IAM 権限不足や設定漏れを平時に
検出できる（訓練時にしか動かないコードの潜伏対策）。特に `dr-scheduler` の
`iam:PassRole` は見落としやすいので、ここで早期に検証する。
