# Terraform サンプル

## 構成

```
terraform/
  modules/
    dr-switch/        入力に従ってリソースを作るだけ。環境依存なし
      variables.tf    functions / network の入力
      iam.tf          ロールとポリシー（for_each）
      lambda.tf       関数定義（for_each）
      network.tf      セキュリティグループ
      eks_access.tf   EKS アクセスエントリ
      outputs.tf
    dr-switch-rbac/   Kubernetes RBAC（1 クラスタ分）
  envs/
    tokyo/            ACTIVE 側。閉塞対象は大阪
      functions.tf    ★ 対象 Lambda の定義（追加・変更はここだけ）
      locals.tf       対象リソースの識別子と ARN
      main.tf         module 呼び出し
      providers.tf    AWS / Kubernetes provider
      variables.tf    別 state から受け取る値
    osaka/            STANDBY 側。閉塞対象は東京
```

## Lambda を追加・変更するとき

**`envs/*/functions.tf` の `local.functions` にエントリを 1 つ足すだけでよい。**
module 配下には手を入れない。

```hcl
"新しい関数名" = {
  handler = "dr_switch.xxx.handlers.yyy"
  env     = { REGION = local.self_region, ... }
  policy = [{
    actions   = ["service:Action"]
    resources = [local.xxx_arn]
  }]
  # timeout = 120   任意。既定 60 秒
  # vpc     = false 任意。既定 true（全関数を VPC 内に配置する方針）
  # eks     = true  任意。既定 false。EKS アクセスエントリを作る
}
```

対象リソースが増えるときは `locals.tf` に名前と ARN の組み立てを足す。
どちらも env 側で完結する。

`policy` のステートメントに `pass_role_service` を付けると、`iam:PassRole` の
渡し先を限定する condition が生成される。

## module の責務

module が受け取るのは `functions`（関数名 -> 定義）とネットワークの設定だけ。
**関数名も環境固有の値も持たない**ので、対象が増えても module の変数は
変わらない。

| module の入力 | 内容 |
|---|---|
| `functions` | 関数名 -> `{ handler, env, policy, timeout, vpc, eks }` |
| `region` | プレフィックスリストの解決に使う |
| `image_uri` | ECR のイメージ URI |
| `vpc_id` / `vpc_subnet_ids` | Lambda の配置先 |
| `interface_endpoint_security_group_ids` | 許可を追加するエンドポイントの SG |
| `eks_cluster_security_group_ids` | クラスタ名 -> マネージド SG |
| `name_prefix` / `rbac_group` / `gateway_endpoint_services` | 任意。既定値あり |

## 対象リソースはリソース参照から取る

`envs/*/locals.tf` で、同一 state のリソースを**参照から**取る。名前を直値で
書くと、リソース名を変えたときに権限がズレる。タイプミスも plan では検出
されず、実行時の権限エラーになるまで気づけない。

```hcl
self_table_names = [for t in aws_dynamodb_table.this : t.name]
self_table_arns  = [for t in aws_dynamodb_table.this : t.arn]
```

**ARN も文字列で組み立てない。** 参照から取ればフォーマットを間違える余地が
無くなる。例外は API Gateway と EventBridge Scheduler で、管理用 ARN の属性が
無いため組み立てが必要（API Gateway の ARN にはアカウント ID が入らず、
コロンが 2 つ続く点に注意）。

依存の順序は Terraform が解決する。`data` と違い、リソース参照なら同じ apply で
作るリソースでも問題ない。`for_each` のキーだけは plan 時に確定している必要が
あるが、`functions` のキーと `endpoints` の文字列はどちらも静的なので問題ない。

### 置き換えが必要なリソース名

以下は**仮の名前**。実際の構成に合わせて置き換えること。

```
aws_vpc.this                   aws_subnet.private
aws_api_gateway_rest_api.this  aws_api_gateway_stage.this
aws_scheduler_schedule_group.this
aws_s3_bucket.this             aws_iam_role.s3_replication
aws_iam_role.scheduler_target
aws_lambda_function.app        aws_lambda_function.pod_restart
aws_dynamodb_table.this        aws_efs_file_system.this
aws_lb.this                    aws_lb_target_group.this
aws_eks_cluster.this           （キーは "a" / "b" を仮置き）
```

`variables.tf` に残しているのは**別 state から受け取るものだけ**。相手
リージョンのリソースと、インターフェースエンドポイントの SG。
`terraform_remote_state` で引く場合は変数を消し、`locals.tf` で
`data.terraform_remote_state.xxx.outputs.yyy` を参照する。

## RBAC を別 module にしている理由

**Kubernetes provider はクラスタごとに 1 インスタンス必要**で、module 内では
`for_each` で provider を切り替えられない。そのためクラスタの数だけ
`dr-switch-rbac` を呼び出し、`providers` で対応する provider を渡す。

```hcl
module "rbac_cluster_a" {
  source     = "../../modules/dr-switch-rbac"
  providers  = { kubernetes = kubernetes.cluster_a }
  namespaces = [for n in local.clusters["tokyo-cluster-a"] : n.name]
  rbac_group = module.dr_switch.rbac_group
}
```

アクセスエントリ（`aws_eks_access_entry`）は AWS provider なので本体 module に
残している。`eks = true` の関数だけが対象になる。

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

**全 Lambda を VPC 内に配置し、関数ごとにセキュリティグループを作る。**
NAT ゲートウェイが無いためパブリックインターネットへは出られず、AWS API へは
VPC エンドポイント経由で到達する。

### 関数ごとに SG を分ける理由

**その関数が到達する先だけに egress を開く。** IAM で叩けるアクションを
絞っていても、経路が開いていることとは別。多層防御として、ネットワーク側でも
最小権限にする。

接続先は `functions` の定義に書く。`logs` は全関数に必要なので module 側で
自動的に付与する。

```hcl
"apigateway-block" = {
  endpoints = ["apigateway"]          # logs は書かない
}
"s3-check" = {
  gateway_endpoints = ["s3"]          # Gateway 型はプレフィックスリスト宛
}
"eks-check" = {
  endpoints    = ["eks", "eks-auth", "sts"]
  eks_clusters = local.cluster_names  # クラスタ SG への 443 とアクセスエントリ
}
```

### 生成されるもの

| 関数 | インターフェースエンドポイント | Gateway | EKS |
|---|---|---|---|
| apigateway-block / enable / check | logs, apigateway | | |
| scheduler-block / enable / check | logs, scheduler | | |
| s3-block / enable / check | logs | s3 | |
| lambda-check | logs, lambda | | |
| dynamodb-check | logs | dynamodb | |
| nlb-check | logs, elasticloadbalancing | | |
| cloudwatch-check | logs, monitoring | | |
| efs-check | logs, elasticfilesystem | | |
| eks-check / rollout-restart | logs, eks, eks-auth, sts | | 2 クラスタ |
| eks-restart-pods | logs, lambda | | |

SG 17 個、ルール 80 本（egress 38 + ingress 38 + Gateway egress 4）。

### エンドポイントの SG はサービス名のマップで渡す

エンドポイントごとに SG が分かれている前提で、関数ごとに必要な
エンドポイントにだけ ingress を追加する。別 state で管理しているため、
`terraform_remote_state` か tfvars で渡す。

```hcl
interface_endpoint_security_group_ids = {
  logs                 = "sg-..."
  apigateway           = "sg-..."
  scheduler            = "sg-..."
  lambda               = "sg-..."
  elasticloadbalancing = "sg-..."
  monitoring           = "sg-..."
  elasticfilesystem    = "sg-..."
  eks                  = "sg-..."
  eks-auth             = "sg-..."
  sts                  = "sg-..."
}
```

`logs` は全関数に必要。見落とすとログが一切出ず、しかも関数自体は
タイムアウトするまで気づけない。

Gateway 型（`s3` / `dynamodb`）はセキュリティグループを持たない。ルート
テーブルに関連付けられていれば到達でき、Lambda 側はプレフィックスリスト宛の
アウトバウンドを許可する。プレフィックスリストは AWS が管理していて常に
存在するため `data` で引いてよい。

### 閉塞系のクロスリージョンアクセス

`apigateway-block` / `scheduler-block` / `s3-block` は相手リージョンの API を
叩く。クロスリージョン PrivateLink は `apigateway` / `scheduler` に未対応の
ため、**相手リージョン側の Interface VPCE へ VPC Peering と Route 53 Resolver
の条件付き転送で到達する**（既存のクロスリージョンエンドポイントアクセス方針）。

boto3 は `region_name` からホスト名を組み立てるだけなので、DNS が相手側
VPCE のプライベート IP に解決されれば**コードの変更は不要**。

この場合、`interface_endpoint_security_group_ids` に渡すのは**相手リージョン側
エンドポイントの SG** になる。

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
