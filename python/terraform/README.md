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
| `network.tf` | セキュリティグループと VPC エンドポイントの許可 |

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
**全関数を VPC 内に配置する方針**なので、`AWSLambdaVPCAccessExecutionRole`
（ENI の作成・削除）も全関数に付ける。

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

## ネットワーク

**全 Lambda を VPC 内に配置する。** NAT ゲートウェイが無いためパブリック
インターネットへは出られず、AWS API へは VPC エンドポイント経由で到達する。

`aws_security_group.dr_lambda` を新規に作り、全関数がこれを使う。

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

Gateway 型（`s3` / `dynamodb`）はセキュリティグループを持たない。ルート
テーブルに関連付けられていれば到達でき、Lambda 側はプレフィックスリスト宛の
アウトバウンドを許可する。

### 追加するルール

| 方向 | 対象 | 内容 |
|---|---|---|
| Lambda SG の egress | 各インターフェースエンドポイントの SG | 443 |
| Lambda SG の egress | EKS クラスタの SG | 443 |
| Lambda SG の egress | s3 / dynamodb のプレフィックスリスト | 443 |
| エンドポイントの SG の ingress | Lambda SG | 443 |
| **EKS クラスタ SG の ingress** | Lambda SG | 443 |

最後の 1 つが要点。**これが無いと kubeconfig を生成できても API サーバへ
到達できない。** 対象は EKS が作成するマネージド SG
（`vpc_config[0].cluster_security_group_id`）。

## タイムアウト

既定は 60 秒。到達不能時の最大 20 秒 ＋ 通常の最大 5 秒 ＋ 余裕。

`eks-restart-pods` だけは呼ばれる側の完了を待つため
`pod_restart_timeout + 60` 秒にしている。`pod_restart_timeout` は
**呼ばれる側の Lambda の Timeout に合わせること**。

## 確認済みの整合性

コード側のハンドラ 17 本と Terraform の関数定義が一致し、各設定クラスが
`required` としている環境変数がすべて渡されていることを機械的に検証済み。
