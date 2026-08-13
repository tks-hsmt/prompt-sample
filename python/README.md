# DR 切替 Lambda 実装メモ

## 構成

| 関数 | ファイル | 対象 | 種別 | 例外 |
|---|---|---|---|---|
| dr-fence | `fence.py` | PEER | 変更 | Retryable / BestEffortFailed |
| dr-activate | `activate.py` | SELF | 変更 | Retryable / Fatal |
| dr-check-readiness | `check_readiness.py` | SELF | 観測 | 投げない |
| dr-check-workload | `check_workload.py` | SELF | 観測 | 投げない |

共通モジュール: `common.py`（設定・例外分類）、`switch_ops.py`（API GW / EventBridge 操作）

4 本とも東京・大阪の**両リージョンにデプロイ**する。実行するのは常に
これから ACTIVE になる側。切替方向は「どのリージョンの Step Functions を
叩いたか」で決まるため、入力に direction を持たない。

作らないもの:

- S3 レプリケーション操作 … 双方向常時 Enabled（案 B）のため切替時の操作なし
- SQS ドレイン確認 … 障害時は待っても解消しないため実施しない
- スケールアップ … 両リージョン同レプリカ数のため不要

## 環境変数（Terraform から注入）

東京デプロイと大阪デプロイで self / peer を入れ替えて同じモジュールを呼ぶ。

```hcl
environment {
  variables = {
    SELF_REGION              = "ap-northeast-3"
    SELF_REST_API_ID         = var.self_rest_api_id
    SELF_STAGE               = var.self_stage
    SELF_EVENT_BUS           = var.self_event_bus
    SELF_HEALTH_URL          = var.self_health_url
    SELF_FUNCTION_NAMES      = jsonencode(var.self_function_names)
    SELF_TABLE_NAMES         = jsonencode(var.self_table_names)
    SELF_TARGET_GROUP_ARNS   = jsonencode(var.self_target_group_arns)
    SELF_MIN_HEALTHY_TARGETS = var.self_min_healthy_targets
    SELF_ALARM_PREFIX        = var.self_alarm_prefix
    SELF_EKS_CLUSTER_NAME    = var.self_eks_cluster_name
    SELF_EKS_NAMESPACES      = jsonencode(var.self_eks_namespaces)
    SELF_EKS_DEPLOYMENTS     = jsonencode(var.self_eks_deployments) # {"ns/name": 3}

    PEER_REGION              = "ap-northeast-1"
    PEER_REST_API_ID         = var.peer_rest_api_id
    PEER_STAGE               = var.peer_stage
    PEER_EVENT_BUS           = var.peer_event_bus
  }
}
```

fence は PEER の 4 変数だけ、activate は SELF の 4 変数だけを参照する。
check 系は SELF のみ。関数ごとに必要なものだけ渡してもよい。

## IAM（変更系と観測系でロールを分ける）

変更系（dr-fence / dr-activate）:

```
apigateway:GET, apigateway:PATCH, apigateway:POST, apigateway:UpdateRestApiPolicy
events:ListRules, events:EnableRule, events:DisableRule
```

観測系（dr-check-*、読み取り専用にできるので定期実行しても安全）:

```
apigateway:GET
lambda:GetFunction, lambda:ListEventSourceMappings
dynamodb:DescribeTable
elasticloadbalancing:DescribeTargetHealth
cloudwatch:DescribeAlarms
eks:DescribeCluster
sts:GetCallerIdentity
```

`apigateway:PATCH` は両リージョンの REST API ARN を Resource に含めること。

## Step Functions への組み込み

```json
"Fence": {
  "Type": "Task",
  "Resource": "arn:aws:states:::lambda:invoke",
  "Parameters": {"FunctionName": "dr-fence", "Payload.$": "$"},
  "Retry": [{
    "ErrorEquals": ["RetryableError", "Lambda.ServiceException",
                    "Lambda.TooManyRequestsException"],
    "IntervalSeconds": 5, "MaxAttempts": 3, "BackoffRate": 2
  }],
  "Catch": [{
    "ErrorEquals": ["BestEffortFailed"],
    "ResultPath": "$.fenceError",
    "Next": "Activate"
  }],
  "Next": "Activate"
}
```

- 閉塞失敗は `ResultPath` に記録して続行（握りつぶさず実行履歴に残す）
- activate の `FatalError` は Catch しない（切替不成立なので停止させる）
- check 系は戻り値の `ready` を `Choice` で判定し、false なら
  `Wait`（30 秒）→ 再実行。EventBridge の反映ラグはこのループで吸収する

## タイムアウト

いずれも待機しない設計なので 30〜60 秒で十分。
長いタイムアウトは、API が応答しない状態で無駄に待つだけになる。

## dry_run

変更系の 2 本は `{"dry_run": true}` で読み取りと「実行予定の操作」の
返却のみ行う。EventBridge Scheduler で週次実行すれば、IAM 権限不足や
設定漏れを平時に検出できる（訓練時にしか動かないコードの潜伏対策）。

## check_workload の依存

`kubernetes` パッケージが必要。Layer またはコンテナイメージで同梱し、
VPC 内（クラスタ API エンドポイントに到達可能なサブネット）に配置する。
実行ロールを EKS アクセスエントリで view 相当にマッピングすること。

## 補足: S3 レプリケーションメトリクス

切替可否のゲートには使わないが、切替後の突合と平時の RPO 可視化のために
`aws_s3_bucket_replication_configuration` の rule に metrics を有効化して
おくこと。東京 -> 大阪ルールの PENDING は宛先である大阪の CloudWatch に
出るため、東京障害中でも大阪側から取り残し量を読める。
