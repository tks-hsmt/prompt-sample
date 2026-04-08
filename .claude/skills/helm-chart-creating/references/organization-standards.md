# 組織標準 (固定ルール)

このファイルは本スキルが**ヒアリング対象としない、自動適用される固定ルール**を定義する。ユーザーの個別要件に関わらず、全ての生成チャートに適用される。

> ⚠️ **このファイルの位置付け**: 現在の内容は CIS Benchmark for Kubernetes、NSA/CISA Kubernetes Hardening Guidance、Pod Security Standards Restricted、Helm Chart Best Practices に基づく**業界標準ベースの叩き台**である。Takeshi さんの組織で別途定めた標準があれば、そのルールでこのファイルを上書きする。

## セキュリティ (Pod Security Standards Restricted 準拠)

**全ワークロードで以下を強制し、ヒアリングしない**:

| パラメータ | 値 | 根拠 |
|---|---|---|
| `podSecurityContext.runAsNonRoot` | `true` | PSS Restricted |
| `containerSecurityContext.runAsNonRoot` | `true` | PSS Restricted |
| `containerSecurityContext.allowPrivilegeEscalation` | `false` | PSS Restricted |
| `containerSecurityContext.readOnlyRootFilesystem` | `true` | CIS Benchmark 5.7.2 |
| `containerSecurityContext.capabilities.drop` | `[ALL]` | PSS Restricted |
| `containerSecurityContext.seccompProfile.type` | `RuntimeDefault` | PSS Restricted |

**追加 capability** (`capabilities.add`): 原則 `[]`。`NET_BIND_SERVICE` のみ追加可 (PSS Restricted 許容範囲)。それ以外を追加する場合は **organization-standards に違反するため明示的にヒアリングで確認する**。

## イメージ管理

| ルール | 内容 |
|---|---|
| イメージ参照 | **digest 必須** (`@sha256:...`)。タグのみ (`:v1.0`) は禁止。`:latest` 禁止 |
| `imagePullPolicy` | `IfNotPresent` (digest 固定運用と整合) |
| プライベートレジストリ認証 | **Workload Identity を優先** (AWS IRSA、GCP Workload Identity、Azure AD Workload Identity)。`imagePullSecrets` はそれが使えない環境のみ |

## ServiceAccount

| ルール | 内容 |
|---|---|
| `serviceAccount.create` | `true` (専用 SA を必ず作成) |
| `automountServiceAccountToken` | `false` (k8s API アクセスが明示されない限り) |
| `rbac.create` | `false` (k8s API アクセスが明示されない限り) |

## 標準ラベル (全リソース必須)

```yaml
app.kubernetes.io/name: <chart-name>
app.kubernetes.io/instance: <release-name>
app.kubernetes.io/version: <appVersion>
app.kubernetes.io/managed-by: Helm
helm.sh/chart: <chart>-<version>
```

**Selector に使うラベル** (`app.kubernetes.io/name`, `app.kubernetes.io/instance`) は **作成後変更不可**のため、絶対に追加・変更しない。

## ロギング

- アプリは **stdout/stderr** に出力する。ファイルログは原則使用しない
- ファイルログが必須の場合は `emptyDir` ボリュームに書き出し、サイドカーで stdout 転送するパターンを検討
- クラスタの集約ログ基盤 (fluentd/fluent-bit DaemonSet 等) が stdout を収集する前提

## メトリクス公開 (該当する場合のみ)

- Prometheus の検出方式: クラスタが Prometheus Operator なら **PodMonitor / ServiceMonitor を推奨**。ただし本スキルは現状 PodMonitor/ServiceMonitor を生成しない
- 標準アノテーション方式 (`prometheus.io/scrape: "true"` 等) は Prometheus Operator なしの環境のみ

## 環境分離

| 環境 | values ファイル | 用途 |
|---|---|---|
| dev | `values-dev.yaml` | 開発、検証 |
| stg | `values-stg.yaml` | ステージング、本番前の最終確認 |
| prod | `values-prod.yaml` | 本番 |

`image.digest` は環境ごとに変わる前提。`replicaCount`、`resources` も環境差が出るのが標準。

## ネットワークポリシー

- クラスタの CNI が NetworkPolicy 対応である場合、**本番環境では NetworkPolicy 有効化を推奨** (デフォルト deny + 必要な通信のみ許可)
- ただし強制ではない (CNI 非対応クラスタもあるため)

## 違反時の挙動

本スキルは上記ルールに違反する設定を **生成してはならない**。ユーザーから違反する要求があった場合:

1. 要求された理由を確認
2. 代替案を提示 (例: root 実行が必要 → init container で chown して非 root で起動)
3. それでも違反が必要なら、計画書に「**組織標準違反**」 セクションを設けて明示し、ユーザーの明示承認を求める
