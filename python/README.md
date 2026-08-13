# DR 切替 Lambda 実装メモ

## 構成

Lambda は **操作するリソース単位**で分割する。1 関数に複数リソースの操作を
まとめない。各ファイルの docstring 冒頭に必要な IAM 権限を明記している。

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

共通モジュール: `common.py`（設定・例外分類・観測系の共通処理）

`dr-s3-replication` は **S3 案 A を採用する場合のみ**デプロイする（後述）。

10 本とも東京・大阪の**両リージョンにデプロイ**する。実行するのは常に
これから ACTIVE になる側。切替方向は「どのリージョンの Step Functions を
叩いたか」で決まるため、入力に direction を持たない。

作らないもの:

- SQS ドレイン確認 … 障害時は待っても解消しないため実施しない
- スケールアップ … 両リージョン同レプリカ数のため不要

## IAM（リソース単位）

観測系（4〜10）はすべて読み取り専用ロールにできる。変更系（1〜3）とは
必ずロールを分けること。観測系は dry_run 定期実行の安全性が上がる。

| 関数 | 必要なアクション | Resource |
|---|---|---|
| dr-apigw | `apigateway:GET` `apigateway:PATCH` `apigateway:POST` `apigateway:UpdateRestApiPolicy` | **両リージョン**の `/restapis/<id>` と配下 |
| dr-scheduler | `scheduler:ListSchedules` `scheduler:GetSchedule` `scheduler:UpdateSchedule` `iam:PassRole` | **両リージョン**の自チームグループのみ／スケジュール実行ロール |
| dr-s3-replication | `s3:GetReplicationConfiguration` `s3:PutReplicationConfiguration` `iam:PassRole` | **両リージョン**のバケット／レプリケーションロール |
| dr-check-apigw | `apigateway:GET` | SELF の `/restapis/<id>/stages/<stage>` |
| dr-check-lambda | `lambda:GetFunction` `lambda:ListEventSourceMappings` | SELF の対象関数／ESM は `*` |
| dr-check-dynamodb | `dynamodb:DescribeTable` | SELF の対象テーブル |
| dr-check-nlb | `elasticloadbalancing:DescribeTargetHealth` `elasticloadbalancing:DescribeTargetGroups` | `*` |
| dr-check-s3 | `s3:ListBucket` `s3:GetReplicationConfiguration` | SELF のバケット |
| dr-check-alarms | `cloudwatch:DescribeAlarms` | `*` |
| dr-check-workload | `eks:DescribeCluster` `sts:GetCallerIdentity` | SELF のクラスタ／`*` |

注意点:

- `dr-scheduler` の `iam:PassRole` は必須。`UpdateSchedule` が
  `Target.RoleArn` を含む全パラメータを要求するため、これがないと失敗する
- `dr-scheduler` の Resource は自チーム専用グループに限定する。default
  グループには他チームのスケジュールが同居しているため、権限としても外す
- `dr-check-workload` の Pod / Node 参照権限は IAM ではなく Kubernetes RBAC
  側（EKS アクセスエントリで view 相当にマッピング）
- S3 は SSE-S3（AES256）で SSE-C 禁止のため、KMS 関連の権限は全関数で不要

## 環境変数（Terraform から注入）

東京デプロイと大阪デプロイで self / peer を入れ替えて同じモジュールを呼ぶ。
関数ごとに必要なものだけ渡してよい。

```hcl
environment {
  variables = {
    SELF_REGION               = "ap-northeast-3"
    SELF_REST_API_ID          = var.self_rest_api_id
    SELF_STAGE                = var.self_stage
    SELF_HEALTH_URL           = var.self_health_url
    SELF_SCHEDULE_GROUP       = var.self_schedule_group   # 自チーム専用グループ
    SELF_SCHEDULE_NAME_PREFIX = ""                        # グループ内全件が対象
    SELF_FUNCTION_NAMES       = jsonencode(var.self_function_names)
    SELF_TABLE_NAMES          = jsonencode(var.self_table_names)
    SELF_TARGET_GROUP_ARNS    = jsonencode(var.self_target_group_arns)
    SELF_ALARM_PREFIX         = var.self_alarm_prefix
    SELF_EKS_CLUSTER_NAME     = var.self_eks_cluster_name
    SELF_EKS_NAMESPACES       = jsonencode(var.self_eks_namespaces)
    SELF_REPLICATION_BUCKETS  = jsonencode(var.self_replication_buckets) # 案 A のみ

    PEER_REGION               = "ap-northeast-1"
    PEER_REST_API_ID          = var.peer_rest_api_id
    PEER_STAGE                = var.peer_stage
    PEER_SCHEDULE_GROUP       = var.peer_schedule_group
    PEER_SCHEDULE_NAME_PREFIX = ""
    PEER_REPLICATION_BUCKETS  = jsonencode(var.peer_replication_buckets) # 案 A のみ
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
    "ErrorEquals": ["BestEffortFailed"],
    "ResultPath": "$.fenceApiGwError",
    "Next": "FenceScheduler"
  }],
  "Next": "FenceScheduler"
}
```

- 閉塞（role=peer）の失敗は `ResultPath` に記録して続行。握りつぶさず実行
  履歴に残す。リソース単位に分かれているので、どれが閉塞できなかったかが
  実行履歴からそのまま分かる
- 開放（role=self）の `FatalError` は Catch しない（切替不成立なので停止）
- 観測系 7 本は `Parallel` で並列実行し、各戻り値の `ready` を `Choice` で
  判定する。false なら `Wait`（30 秒）→ 再実行。スケジュール有効化や
  API GW 再デプロイの反映ラグはこのループで吸収する
- **`dr-check-nlb` の結果だけで開放判断をしないこと**。ヘルスチェックが
  TCP のため、`dr-check-workload` と併せて両方 ready を条件にする（後述）

## フェーズ順序

```
Fence(peer): apigw -> scheduler          # 失敗許容
  [案 A のみ] s3-replication(self, enable=true)
  [案 A のみ] s3-replication(peer,  enable=false)   # 失敗許容
Check(self): apigw / lambda / dynamodb / nlb / s3 / alarms / workload  # 並列
Activate(self): scheduler -> apigw       # 失敗は致命的
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

## EventBridge Scheduler

イベント駆動は EventBridge **Rules ではなく Scheduler**（スケジュール）を
使っている。`events` ではなく `scheduler` クライアントを叩く。

自チーム専用のスケジュールグループが独立して存在するため、
`SCHEDULE_GROUP` にそのグループ名を指定し、`SCHEDULE_NAME_PREFIX` は空でよい。
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
`HealthCheckPort` は `traffic-port`（トラフィックポートと同一番号）。
ターゲットグループは 2 つ（Port 1 / 9116）で、現状すべて healthy。

IP モードでは NLB が Pod IP へ直接トラフィックを送るため、トラフィックは
kube-proxy を経由せず、`externalTrafficPolicy` は判定に関係しない。
Controller は Endpoints / EndpointSlices からターゲットを解決し、一覧に無い
ターゲットは即座に登録解除する。したがって

    登録されているターゲット ≒ Ready な Pod

### 判定

`dr-check-nlb` は「登録済みのターゲットがすべて健全か」だけを見る。

    unhealthy == 0  かつ  initial == 0  かつ  healthy >= 1

**必要数を満たしているかの判定は `dr-check-workload` に一本化**している。
必要数を外から与える設定（`MIN_HEALTHY_TARGETS`）は持たない。Deployment 自身が
`spec.replicas` を持っているため、設定と実態がずれる余地を作らない。
これにより、2 つのターゲットグループが別々の Deployment を向いているか
どうかを気にする必要もなくなる。

`initial`（登録処理が進行中）を許容しないのは、早すぎる開放を防ぐため。
EndpointSlice の更新は ELB のターゲット登録より速く進むので、Pod が Ready
でも NLB 側が `initial` のままの時間がある。

### dr-check-workload との併用

Step Functions の `Choice` は両方が `ready: true` であることを条件にする。
Hybrid Node の Ready 状態や Pending 状態の Pod はターゲットグループに
現れないため、`dr-check-nlb` だけでは判定材料が足りない。

## EKS ワークロードの判定

`dr-check-workload` は `EKS_NAMESPACES` の各 namespace の Deployment を
列挙し、`status.ready_replicas >= spec.replicas` で判定する。

- 必要数は Deployment 自身が持っているので設定値として与えない
- Deployment 名も列挙するため、設定は namespace のリストだけで済む
- `status.replicas`（作成済み数）ではなく `ready_replicas` を見る。前者では
  Pod が起動しただけで readinessProbe を通っていない状態を通してしまう

検出できないもの: 「本来 3 のはずが `spec.replicas` が 1 になっている」ような
平時の構成ドリフト。切替の瞬間に気づいても打つ手がない種類の問題なので、
dry_run の定期実行や Terraform のドリフト検知で拾う。

## check_workload の依存

既存の Pod 再起動 Lambda と同じ方式（`aws eks update-kubeconfig`）を使う。

- AWS CLI と `kubernetes` パッケージを Layer またはコンテナイメージに同梱
- クラスタ API エンドポイントはプライベートのみのため、到達可能な
  VPC・サブネット・セキュリティグループに配置する（既存 Lambda と同じ設定）
- 実行ロールを EKS アクセスエントリで view 相当にマッピングする
- CA 証明書とトークン取得は CLI が肩代わりするため、Python 側の実装は不要
  （kubeconfig の exec プラグインが `aws eks get-token` を都度実行する）

## タイムアウト

いずれも待機しない設計なので 30〜60 秒で十分。
長いタイムアウトは、API が応答しない状態で無駄に待つだけになる。

## dry_run

変更系 3 本は `{"dry_run": true}` で読み取りと「実行予定の操作」の返却のみ
行う。EventBridge Scheduler で週次実行すれば、IAM 権限不足や設定漏れを平時に
検出できる（訓練時にしか動かないコードの潜伏対策）。特に `dr-scheduler` の
`iam:PassRole` は見落としやすいので、ここで早期に検証する。

## 未確認の前提（要確認）

- **SQS のコンシューマ** … Lambda のイベントソースマッピングで消費している
  前提で `dr-check-lambda` に ESM 確認を入れている。EKS Pod 側でポーリング
  しているなら、この確認は無意味
- **S3 の案 A / 案 B** … 未確定のため両対応
