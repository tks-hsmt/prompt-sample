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
      eks_access.tf   アクセスエントリとアクセスポリシー
      outputs.tf
  envs/
    tokyo/            ACTIVE 側。閉塞対象は大阪
      functions.tf    ★ 対象 Lambda の定義（追加・変更はここだけ）
      locals.tf       対象リソースの識別子と ARN
      main.tf         module 呼び出し
      providers.tf    AWS provider
      variables.tf    別 state から受け取る値
    osaka/            STANDBY 側。閉塞対象は東京
```

## 段階的な構築

依存先の構築状況で 3 段階に分かれる。**未構築でも plan / apply が通る**よう、
`data` ブロックごと `count` で制御する。`try()` では防げない（state ファイルが
読めない時点で失敗するため）。

| 段階 | フラグ | 作られるもの |
|---|---|---|
| **1** | すべて `false` | Lambda 14 本・ロール・SG・エンドポイント向けルール |
| **2** | `external_eks_ready = true` | ＋別 state の EKS クラスタも確認・再起動の対象に |
| **3** | `peer_ready = true` | ＋閉塞系 3 本と相手リージョン向け egress |

**VPC エンドポイントは環境チームが先に作るため、常に存在する前提**でよい。
フラグを設けず `data` で引く。サービス名のキーが渡されていなければ設定漏れ
なので、`lookup` で握りつぶさず明示的に失敗させる。

### 段階 3 は両リージョンが揃ってから

東京と大阪が**互いの state を参照する**ので循環する。初回は両方 `false` で
構築し、双方が揃ってから `true` にして再適用する。

| 関数 | 段階 |
|---|---|
| `apigateway-enable` / `check`、`scheduler-enable` / `check`、`s3-enable` / `check` | 1 |
| `lambda-check`、`dynamodb-check`、`nlb-check`、`cloudwatch-check`、`efs-check` | 1 |
| `eks-check`、`eks-rollout-restart`、`eks-restart-pods` | 1 |
| **`apigateway-block`、`scheduler-block`、`s3-block`** | **3** |

### 未構築時の module の挙動

- `eks_cluster_security_group_ids` にキーが無いクラスタは、アクセスエントリも SG ルールも作らない
- `peer_endpoint_cidr_blocks` が空なら、相手リージョン向け egress を作らない

module に `count` は不要。渡された `functions` の分だけ作るので、閉塞系を
除けばそれだけ作られない。

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

## 対象リソースの取り方

**state の所在で取り方を変える。**

| 所在 | 取り方 | 例 |
|---|---|---|
| 同一 state | リソース参照 | `aws_dynamodb_table.this` |
| 別 state（output あり） | `terraform_remote_state` | 相手リージョン、別 state の EKS クラスタ |
| 別 state（output なし） | `data` ソース | VPC エンドポイント |

### 同一 state はリソース参照

名前を直値で書くと、リソース名を変えたときに権限がズレる。タイプミスも
plan では検出されず、実行時の権限エラーになるまで気づけない。

```hcl
self_table_names = [for t in aws_dynamodb_table.this : t.name]
self_table_arns  = [for t in aws_dynamodb_table.this : t.arn]
```

**ARN も文字列で組み立てない。** 参照から取ればフォーマットを間違える余地が
無くなる。例外は API Gateway と EventBridge Scheduler で、管理用 ARN の属性が
無いため組み立てが必要（API Gateway の ARN にはアカウント ID が入らず、
コロンが 2 つ続く点に注意）。

**依存の順序は Terraform が解決する。** `data` と違い、リソース参照なら同じ
apply で作るリソースでも問題ない。同一 state のものに `data` を使うと、初回
apply でまだ存在せず失敗する。

同一 state の参照に output は不要。output は別 state から参照させるためのもの。

### 別 state は先に作られている必要がある

`terraform_remote_state` でも `data` でも、**参照先が既に存在していないと
plan が失敗する**。これは書き方の問題ではなく、state が分かれていることの
帰結で、変数に手打ちしても順序の制約は変わらない。

手打ちを避ける利点は、**相手側で作り直したときに自動追従する**こと。

### VPC エンドポイントは data で引く

output が無いため `data` で引く。サービス名は
`com.amazonaws.<region>.<service>` の固定形式で、引くサービス名は
`functions` の `endpoints` に書いたものから自動的に集める。

```hcl
endpoint_services = distinct(concat(
  ["logs"],
  flatten([for f in local.functions : f.endpoints]),
))

data "aws_vpc_endpoint" "interface" {
  for_each     = toset(local.endpoint_services)
  vpc_id       = aws_vpc.this.id
  service_name = "com.amazonaws.${local.self_region}.${each.key}"
}
```

**エンドポイントを追加しても、`functions` に `endpoints` を書けば自動で
引かれる。** `locals.tf` にも手を入れない。

SG は複数付いていてもよい。module 側で (関数, エンドポイント, SG) の
3 つ組でルールを作る。

### 置き換えが必要なもの

以下は**仮の名前**。実際の構成に合わせて置き換えること。

```
同一 state のリソース名
  aws_vpc.this                   aws_subnet.private
  aws_api_gateway_rest_api.this  aws_api_gateway_stage.this
  aws_scheduler_schedule_group.this
  aws_s3_bucket.this             aws_iam_role.s3_replication
  aws_iam_role.scheduler_target
  aws_lambda_function.app        aws_lambda_function.pod_restart
  aws_dynamodb_table.this        aws_efs_file_system.this
  aws_lb.this                    aws_lb_target_group.this
  aws_eks_cluster.this

別 state の output 名
  相手リージョン  rest_api_id / stage_name / schedule_group / schedule_role_arn
                  replication_buckets / replication_bucket_arns / replication_role_arn
  EKS クラスタ    cluster_name / cluster_arn / cluster_security_group_id
```

`variables.tf` に残っているのは**別 state のバックエンド情報と `image_uri`
だけ**。

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

### Route 53 はサービス名にリージョンが入らない

**Route 53 の API エンドポイントは us-east-1 の 1 つだけ**（公式に「北京・
寧夏以外のリージョンでは us-east-1 を指定する」と明記）。他リージョンからは
**クロスリージョン Interface VPC エンドポイント**で接続する。

そのため VPC エンドポイントのサービス名が
**`com.amazonaws.route53`**（リージョンを含まない）になる。

`locals.tf` の `global_endpoint_services` にサービス名を列挙して、名前の
組み立てを分ける。

```hcl
global_endpoint_services = ["route53"]

endpoint_service_names = {
  for svc in local.endpoint_services :
  svc => (contains(local.global_endpoint_services, svc)
    ? "com.amazonaws.${svc}"
    : "com.amazonaws.${local.self_region}.${svc}")
}
```

`functions.tf` 側は `endpoints = ["route53"]` のままでよい。DNS 名の組み立て
規則は関数定義の関心事ではない。

なお **Route 53 の PrivateLink 対応は 2025 年 11 月に提供開始**された比較的
新しい機能。

### 閉塞系のクロスリージョンアクセス

`apigateway-block` / `scheduler-block` / `s3-block` は**相手リージョンの API を
叩く**ので、到達先も相手リージョンのエンドポイントになる。

クロスリージョン PrivateLink は `apigateway` / `scheduler` に未対応のため、
**相手リージョン側の Interface VPCE へ VPC Peering と Route 53 Resolver の
条件付き転送で到達する**（既存のクロスリージョンエンドポイントアクセス方針）。

boto3 は `region_name` からホスト名を組み立てるだけなので、DNS が相手側
VPCE のプライベート IP に解決されれば**コードの変更は不要**。

```hcl
"apigateway-block" = {
  peer_endpoints = ["apigateway"]   # endpoints ではなく peer_endpoints
}
```

**`s3-block` は Gateway 型を使えない。** Gateway 型は VPC のルートテーブルに
紐づき、**同一リージョンにしかルーティングしない**。相手リージョンの S3 へは
Interface エンドポイント経由になる。

| 関数 | 自リージョン | 相手リージョン |
|---|---|---|
| `s3-block` | logs | **s3（Interface）** |
| `s3-enable` / `s3-check` | logs ＋ s3（Gateway） | — |

#### CIDR で書く理由

**リージョン間 VPC ピアリングでは相手リージョンの SG を参照できない。**
公式に「別リージョンのピア VPC のセキュリティグループは参照できない。代わりに
ピア VPC の CIDR ブロックを使う」と明記されている。

そのため `peer_endpoint_cidr_blocks`（相手側エンドポイントが居るサブネットの
CIDR）を渡し、egress を CIDR で書く。

**相手側エンドポイントの SG に対する ingress（自 VPC の CIDR からの 443）は、
この module では作れない。** 相手リージョンの state が管理する範囲になる。

## EKS の権限

### 前提

クラスタの `authenticationMode` が **`API` または `API_AND_CONFIG_MAP`** で
あること。`CONFIG_MAP`（EKS API の既定）ではアクセスエントリを作成できない。
一度アクセスエントリ方式を有効にすると元に戻せない。

```bash
aws eks describe-cluster --name <cluster> --query 'accessConfig.authenticationMode'
```

### 付与するもの

`aws_eks_access_entry` でロールをクラスタに登録し、
`aws_eks_access_policy_association` で**マネージドのアクセスポリシーを
namespace スコープ**で付与する。

| 関数 | ポリシー | スコープ |
|---|---|---|
| `eks-check` | `AmazonEKSViewPolicy` | 対象の全 namespace |
| `eks-rollout-restart` | `AmazonEKSEditPolicy` | **`restart_targets` がある namespace のみ** |

`restart_targets` が空の namespace には Edit を付けない。確認だけする
クラスタには View しか付かない。

### 自前の Role / RoleBinding を使わない理由

Kubernetes provider が必要になり、クラスタごとに provider の alias を切る
ことになる（module 内では `for_each` で provider を切り替えられないため、
クラスタの数だけ module を呼び出す形になる）。Terraform の適用にクラスタへの
到達性も要る。

権限は自前 Role の方が狭くできる（`list` / `patch` のみ）が、`Edit` が余分に
許可するのは Pod の削除やリソース作成で、**ここで動くのは自分たちが書いた
コードだけ**。コードは `list_namespaced_deployment` と
`patch_namespaced_deployment` しか呼ばない。

なお `patch` を許可するポリシーは `AmazonEKSEditPolicy` しかなく、
**自前のアクセスポリシーは作成できない**ため、`rollout_restart` に関しては
選択肢が無い。

## タイムアウト

既定は 60 秒。到達不能時の最大 20 秒 ＋ 通常の最大 5 秒 ＋ 余裕。

`eks-restart-pods` だけは呼ばれる側の完了を待つため
`pod_restart_timeout + 60` 秒にしている。`pod_restart_timeout` は
**呼ばれる側の Lambda の Timeout に合わせること**。

## 確認済みの整合性

コード側のハンドラ 17 本と `local.functions` が一致し、`resource` を定義する
ファイルに関数名の個別記述が無いことを機械的に検証済み。
