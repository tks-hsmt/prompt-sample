# Terraform サンプル

東京・大阪の両リージョンに同じ構成をデプロイする。閉塞系（block）だけが
相手リージョンのリソースを操作するため、そこだけ `peer_*` の値を使う。

## 関数を追加・変更するとき

**`functions.tf` の `local.functions` にエントリを 1 つ足すだけでよい。**
ロール・ポリシー・関数定義・RBAC はすべて `for_each` が生成するので、
`resource` を定義しているファイルには手を入れない。

```hcl
"新しい関数名" = {
  handler = "dr_switch.xxx.handlers.yyy"
  env     = { REGION = var.self_region, ... }
  policy = [{
    actions   = ["service:Action"]
    resources = [local.xxx_arn]
  }]
  # timeout = 120   任意。既定は local.default_timeout（60 秒）
  # vpc     = false 任意。既定は true（全関数を VPC 内に配置する方針）
}
```

`policy` のステートポイントに `pass_role_service` を付けると、
`iam:PassRole` の渡し先を限定する condition が生成される。

## ファイル

| ファイル | 内容 | 関数追加時 |
|---|---|---|
| **`functions.tf`** | **関数ごとの handler / env / policy** | **ここだけ変更** |
| `arns.tf` | 変数から ARN を組み立てる | ARN の種類が増えたときのみ |
| `variables.tf` | 入力変数 | 変数が増えたときのみ |
| `iam.tf` | ロールとポリシーの生成（`for_each`） | 変更不要 |
| `lambda.tf` | 関数定義（`for_each`） | 変更不要 |
| `network.tf` | セキュリティグループと VPC エンドポイントの許可 | 変更不要 |
| `eks_access.tf` | EKS アクセスエントリと Kubernetes RBAC | 変更不要 |

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

全関数に `AWSLambdaBasicExecutionRole`（CloudWatch Logs）と、VPC 配置のため
`AWSLambdaVPCAccessExecutionRole`（ENI の作成・削除）を付与する。

### `Resource: "*"` にせざるを得ないもの

`elasticloadbalancing:Describe*` / `cloudwatch:DescribeAlarms` /
`sts:GetCallerIdentity` はリソースレベル権限に対応しない。AWS のマネージド
ポリシー `AmazonECSInfrastructureRolePolicyForLoadBalancers` でも、`Describe`
系だけ `"*"` で、`RegisterTargets` 等は ARN 指定という使い分けになっている。

### `iam:PassRole` の注意

`scheduler-block` / `scheduler-enable` の `iam:PassRole` は**必須**。
`UpdateSchedule` が `Target.RoleArn` を含む全パラメータを要求するため、
これがないと失敗する。他のどの関数にも不要な権限なので見落としやすい。

## ARN の組み立て

対象リソースの ID を変数で受け取り、`arns.tf` で ARN を文字列として組み立てる。
**同一 state でリソースを管理しているなら、変数にリソース参照を渡すこと。**

```hcl
self_rest_api_id = aws_api_gateway_rest_api.this.id
```

## data ソースを使わない箇所

**自チームが Terraform で管理するリソースは `data` で引かない。** 同じ
Terraform で作る構成だと、初回 apply 時にまだ存在せず失敗する。

| 対象 | 渡し方 |
|---|---|
| EKS のマネージド SG | `eks_cluster_security_group_ids`（変数） |
| インターフェースエンドポイントの SG | `interface_endpoint_security_group_ids`（変数） |

残っている `data` は 3 つで、いずれも自チームが作るリソースではない。

- `aws_caller_identity` … 呼び出し元の情報
- `aws_iam_policy_document` … ローカルで JSON を組み立てるだけ。API 呼び出しなし
- `aws_ec2_managed_prefix_list` … AWS が管理し常に存在する

なお `for_each` のキーは plan 時に確定している必要がある。`data` の結果を
`for_each` に渡すと「キーが事前に確定できない」というエラーになるため、
変数または locals 由来の値を使う。

## ネットワーク

**全 Lambda を VPC 内に配置する。** NAT ゲートウェイが無いためパブリック
インターネットへは出られず、AWS API へは VPC エンドポイント経由で到達する。

### 必要な経路

| 接続先 | 用途 | 種別 |
|---|---|---|
| `logs` | **全関数**のログ出力 | Interface |
| `apigateway` | apigateway 系 3 関数 | Interface |
| `scheduler` | scheduler 系 3 関数 | Interface |
| `elasticloadbalancing` | nlb-check | Interface |
| `monitoring` | cloudwatch-check | Interface |
| `lambda` | lambda-check / eks-restart-pods | Interface |
| `elasticfilesystem` | efs-check | Interface |
| `eks` | eks 系 2 関数 | Interface |
| `eks-auth` | eks 系 2 関数（トークン取得） | Interface |
| `sts` | eks 系 2 関数 | Interface |
| `s3` | s3 系 3 関数 | **Gateway** |
| `dynamodb` | dynamodb-check | **Gateway** |

`logs` は全関数に必要。見落とすとログが一切出ず、しかも関数自体は
タイムアウトするまで気づけない。

### 閉塞系のクロスリージョンアクセス

`apigateway-block` / `scheduler-block` / `s3-block` は相手リージョンの API を
叩く。クロスリージョン PrivateLink は `apigateway` / `scheduler` に未対応の
ため、**相手リージョン側の Interface VPCE へ VPC Peering と Route 53 Resolver
の条件付き転送で到達する**（既存のクロスリージョンエンドポイントアクセス方針）。

boto3 は `region_name` からホスト名を組み立てるだけなので、DNS が相手側
VPCE のプライベート IP に解決されれば**コードの変更は不要**。

### 追加するルール

| 方向 | 対象 | 内容 |
|---|---|---|
| Lambda SG の egress | 各インターフェースエンドポイントの SG | 443 |
| Lambda SG の egress | EKS クラスタの SG | 443 |
| Lambda SG の egress | s3 / dynamodb のプレフィックスリスト | 443 |
| エンドポイントの SG の ingress | Lambda SG | 443 |
| **EKS クラスタ SG の ingress** | Lambda SG | 443 |

最後の 1 つが要点。**これが無いと kubeconfig を生成できても API サーバへ
到達できない。**

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

コード側のハンドラ 17 本と `local.functions` が一致し、`resource` を定義する
ファイルに関数名の個別記述が無いことを機械的に検証済み。
