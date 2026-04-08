# 振る舞いパターン: クラウドリソースアクセス

アプリが AWS/GCP/Azure のマネージドサービス (S3、DynamoDB、GCS、KeyVault、SQS 等) にアクセスする場合の認証構成。

## 該当判定

- アプリがクラウドリソース (S3, DynamoDB, RDS, GCS, KeyVault, Service Bus 等) にアクセス
- ECR/GAR/ACR からプライベートイメージを取得
- ユーザーが「IRSA」 「Workload Identity」 「IAM Role」 等を言及

## ワークロード別の適用

| WL | 該当度 |
|---|---|
| 全 WL | ✅ クラウドアクセスがあれば |

---

## 認証方式: Workload Identity (推奨)

`organization-standards.md` の通り、**Workload Identity 系を必ず優先**する。Secret 不要。

| クラウド | 仕組み | アノテーション例 |
|---|---|---|
| **AWS EKS** | IRSA (IAM Roles for Service Accounts) | `eks.amazonaws.com/role-arn: arn:aws:iam::ACCT:role/MY-ROLE` |
| **AWS EKS Pod Identity** | Pod Identity Agent (新方式) | アノテーション不要 (PodIdentityAssociation で設定) |
| **GCP GKE** | Workload Identity | `iam.gke.io/gcp-service-account: sa@proj.iam.gserviceaccount.com` |
| **Azure AKS** | Azure AD Workload Identity | `azure.workload.identity/client-id: <client-uuid>` (Pod label も必要) |

### Workload Identity の構成

1. クラウド側で IAM Role / Service Account を作成
2. その Role/SA に必要な権限をアタッチ (S3 read 等)
3. k8s 側で ServiceAccount にアノテーションを付与
4. Pod がその ServiceAccount を使う
5. アプリ SDK (AWS SDK 等) が自動で認証情報を取得

---

## 認証方式: Secret ベース (非推奨、フォールバック)

Workload Identity が使えない環境のみ。

| 用途 | 仕組み |
|---|---|
| AWS Access Key/Secret | Secret に格納し環境変数で注入 |
| GCP Service Account JSON | Secret にファイルとして格納しマウント |
| Azure Connection String | Secret に格納し環境変数で注入 |

**問題点**: Secret のローテーション、漏洩リスク、Git 管理難。

---

## 能動的提案

### 1. クラウドリソースアクセスの判明時

ユーザーが「S3 にバックアップ」「DynamoDB から読み込み」 等を言及したら、即座に能動提案:

> 「S3 アクセスとのことなので、認証方式を確認させてください:
> - クラスタは EKS ですか? (IRSA or Pod Identity を推奨)
> - GKE なら Workload Identity を推奨します
> - いずれの場合も Secret 不要で、ServiceAccount にアノテーションを付与する形になります
> - アクセス先の S3 バケット名と必要な権限 (read-only / read-write) を教えてください」

### 2. ECR/GAR/ACR からのイメージ取得

`imagePullSecrets` ではなく Workload Identity を能動提案:

> 「ECR からのイメージ取得は IRSA で認証することを推奨します。`imagePullSecrets` は Secret 管理が必要なため、Workload Identity 化を優先します」

### 3. 必要な IAM 権限の最小化

Least privilege を能動提案:

> 「IAM Role の権限は最小限で構成することを推奨します。
> - S3 read-only なら `s3:GetObject`, `s3:ListBucket` のみ
> - 特定バケットに限定 (`Resource: arn:aws:s3:::my-bucket/*`)」

---

## Phase 1 で確認すべき項目

| 項目 | 例 |
|---|---|
| クラウドプロバイダ | AWS / GCP / Azure |
| アクセス先サービス | S3, DynamoDB, GCS 等 |
| 必要な権限 | read / write / 特定リソースのみ |
| クラスタ種別 | EKS / GKE / AKS / セルフホスト |
| Workload Identity 利用可否 | クラスタが対応しているか |
| IAM Role 作成方法 | Terraform / CloudFormation / 手動 |

---

## 設定例

### AWS EKS + IRSA + S3 access

```yaml
serviceAccount:
  create: true
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/my-app-s3-access

extraEnv:
  - name: AWS_REGION
    value: ap-northeast-1
  - name: S3_BUCKET
    value: my-app-data
```

事前に AWS 側で IAM Role `my-app-s3-access` を作成し、OIDC trust policy で当該 ServiceAccount を信頼するよう設定。

### GCP GKE + Workload Identity + GCS access

```yaml
serviceAccount:
  create: true
  annotations:
    iam.gke.io/gcp-service-account: my-app@my-project.iam.gserviceaccount.com
```

事前に GCP 側で GCP SA を作成し、k8s SA との Workload Identity binding を設定。

---

## よくある落とし穴 (Phase 2 セルフチェック対象)

- **Workload Identity が使えるのに Secret ベース認証**: 不要なリスク
- **`automountServiceAccountToken: false` のままで Workload Identity**: トークンマウントが必要 (Workload Identity の場合は `true` に変更が必要なことがある)
- **IAM Role の権限が広すぎ**: Least privilege 違反、セキュリティリスク
- **AWS Access Key を values にハードコード**: Git に commit されて漏洩
- **クラスタ側の OIDC Provider 未設定**: IRSA が動作しない (前提条件確認)
- **アクセス先リソースが別リージョン/プロジェクト**: クロスアカウント設定が必要
