# Terraform サンプル

東京・大阪の両リージョンに同じ構成をデプロイする。閉塞系（block）だけが
相手リージョンのリソースを操作するため、そこだけ `peer_*` の値を使う。

## ファイル

| ファイル | 内容 |
|---|---|
| `variables.tf` | 入力変数 |
| `iam.tf` | 実行ロールと最小権限 |
| `eks_access.tf` | EKS アクセスエントリと Kubernetes RBAC |
| `lambda.tf` | 関数定義（17 本） |

## 権限の一覧

| 関数 | アクション | Resource |
|---|---|---|
| apigateway-block | `apigateway:GET` `PATCH` | PEER ステージ |
| apigateway-enable | `apigateway:GET` `PATCH` | SELF ステージ |
| apigateway-check | `apigateway:GET` | SELF の API とステージ |
| scheduler-block | `scheduler:ListSchedules` `GetSchedule` `UpdateSchedule` `iam:PassRole` | PEER グループ／実行ロール |
| scheduler-enable | 同上 | SELF |
| scheduler-check | `scheduler:GetScheduleGroup` `ListSchedules` | SELF グループ |
| s3-block | `s3:GetReplicationConfiguration` `PutReplicationConfiguration` `iam:PassRole` | PEER バケット／レプリケーションロール |
| s3-enable | 同上 | SELF |
| s3-check | `s3:GetReplicationConfiguration` | SELF バケット |
| lambda-check | `lambda:GetFunctionConfiguration` | SELF 対象関数 |
| dynamodb-check | `dynamodb:DescribeTable` | SELF 対象テーブル |
| nlb-check | `elasticloadbalancing:DescribeLoadBalancers` `DescribeTargetHealth` | `*` |
| cloudwatch-check | `cloudwatch:DescribeAlarms` | `*` |
| efs-check | `elasticfilesystem:DescribeFileSystems` `DescribeMountTargets` | SELF ファイルシステム |
| eks-check | `eks:DescribeCluster` `sts:GetCallerIdentity` | SELF クラスタ／`*` |
| eks-rollout-restart | 同上（＋ Kubernetes RBAC の `patch`） | 同上 |
| eks-restart-pods | `lambda:InvokeFunction` | 再起動関数 |

全関数に `AWSLambdaBasicExecutionRole`（CloudWatch Logs）を付与する。
`eks-check` と `eks-rollout-restart` は VPC 配置するため
`AWSLambdaVPCAccessExecutionRole` も付ける。

### `Resource: "*"` にせざるを得ないもの

`elasticloadbalancing:Describe*` / `cloudwatch:DescribeAlarms` /
`sts:GetCallerIdentity` はリソースレベル権限に対応しない。AWS のマネージド
ポリシー `AmazonECSInfrastructureRolePolicyForLoadBalancers` でも、`Describe`
系だけ `"*"` で、`RegisterTargets` 等は ARN 指定という使い分けになっている。

### `iam:PassRole` の注意

`scheduler-block` / `scheduler-enable` の `iam:PassRole` は**必須**。
`UpdateSchedule` が `Target.RoleArn` を含む全パラメータを要求するため、
これがないと失敗する。他のどの関数にも不要な権限なので見落としやすい。

`iam:PassedToService` 条件で渡し先を限定している。

## Kubernetes RBAC

マネージドのアクセスポリシー（`AmazonEKSViewPolicy`）は使わない。

- `cluster` スコープ … 全 namespace の全リソースが読めてしまい広すぎる
- `namespace` スコープ … 必要な権限を過不足なく表現できない

`kubernetesGroups` でグループにマッピングし、namespace ごとの `Role` と
`RoleBinding` を自前で作る。`check` は `list` のみ、`rollout_restart` は
`patch` を別 Role で付与する。

Node（クラスタスコープ）を確認しない設計なので、**`ClusterRoleBinding` は不要**。

## タイムアウト

既定は 60 秒。到達不能時の最大 20 秒 ＋ 通常の最大 5 秒 ＋ 余裕。

`eks-restart-pods` だけは呼ばれる側の完了を待つため
`pod_restart_timeout + 60` 秒にしている。`pod_restart_timeout` は
**呼ばれる側の Lambda の Timeout に合わせること**。

## 確認済みの整合性

コード側のハンドラ 17 本と Terraform の関数定義が一致し、各設定クラスが
`required` としている環境変数がすべて渡されていることを機械的に検証済み。
