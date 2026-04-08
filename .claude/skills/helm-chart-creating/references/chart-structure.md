# Helm チャート構造のベストプラクティス

パラメータに紐づかない **構造レベル** のベストプラクティスを定義する。テンプレートに既に実装済みのため、本ファイルは「変更禁止領域」 と「設計意図」 の参照用。

## ディレクトリ構造

```
<chart-name>/
├── Chart.yaml                  # チャートメタデータ
├── values.yaml                 # デフォルト値
├── values-dev.yaml             # 開発環境差分
├── values-stg.yaml             # ステージング環境差分
├── values-prod.yaml            # 本番環境差分
├── values.schema.json          # values.yaml のスキーマ検証
├── README.md.gotmpl            # helm-docs 用テンプレート
└── templates/
    ├── _helpers.tpl
    ├── <workload>.yaml         # メインワークロード (deployment.yaml 等)
    ├── service.yaml
    ├── serviceaccount.yaml
    ├── rbac.yaml               # rbac.create=true の場合
    ├── configmap.yaml          # 必要な場合
    ├── secret.yaml             # 必要な場合
    ├── ingress.yaml            # ingress.enabled=true の場合
    ├── hpa.yaml
    ├── pdb.yaml
    ├── networkpolicy.yaml
    └── NOTES.txt
```

**原則**: 1 リソース 1 ファイル、ファイル名は小文字、k8s リソース名をそのまま使用 (複数形にしない)。

## Chart.yaml の規則

| フィールド | 規則 |
|---|---|
| `apiVersion` | `v2` 固定 |
| `name` | チャート名 (lowercase, ハイフン区切り) |
| `description` | アプリの 1 行説明 |
| `type` | `application` |
| `version` | チャート自体の SemVer |
| `appVersion` | アプリのバージョン (digest と整合) |

## values.yaml と values.schema.json

- **`values.yaml`**: 全パラメータのデフォルト値とコメント
- **`values.schema.json`**: 必須項目、型、enum、パターン (例: `image.digest` は `^sha256:[a-f0-9]{64}$`) を強制
- **`helm install --debug`** で schema 違反は事前に検出される

## 環境別 values の分割方針

- **`values.yaml`**: 全環境共通のデフォルト
- **`values-{dev,stg,prod}.yaml`**: 環境固有差分のみ (重複させない)
- 環境によって変わる項目 (`replicaCount`, `resources`, `image.digest` 等) は環境別ファイルで上書き

## _helpers.tpl の慣習

標準ヘルパーを定義:

| 関数 | 用途 |
|---|---|
| `<chart>.name` | チャート名 |
| `<chart>.fullname` | release-chart の組み合わせ (リソース名用) |
| `<chart>.chart` | チャート名+バージョン |
| `<chart>.labels` | 標準ラベルセット |
| `<chart>.selectorLabels` | Selector 専用ラベル (不変) |
| `<chart>.serviceAccountName` | 使用する SA 名 |

## ラベル規則

全リソースに以下の標準ラベルを付与:

```yaml
app.kubernetes.io/name: <chart-name>
app.kubernetes.io/instance: <release-name>
app.kubernetes.io/version: <appVersion>
app.kubernetes.io/managed-by: Helm
helm.sh/chart: <chart>-<version>
```

カスタムラベル (チーム名、コスト管理タグ等) は `metadata.md` の `commonLabels` 経由で追加。

## Selector の不変性 ⚠️ 重要

`Deployment.spec.selector.matchLabels` と `StatefulSet.spec.selector.matchLabels` は **作成後変更不可** (Helm upgrade 時にエラー)。

- `selectorLabels` ヘルパーは **app.kubernetes.io/name と app.kubernetes.io/instance のみ** を返す
- バージョン情報やカスタムラベルは selector に含めない (不変要件のため)

## セキュリティ原則

本スキルは Pod Security Standards **Restricted** プロファイル準拠を強制:

- `runAsNonRoot: true` (必須)
- `allowPrivilegeEscalation: false` (必須)
- `readOnlyRootFilesystem: true` (本スキル独自要件、CIS 推奨)
- `capabilities.drop: [ALL]` (必須、追加可は `NET_BIND_SERVICE` のみ)
- `seccompProfile.type: RuntimeDefault` (必須)

## テンプレート内の条件分岐

条件分岐は最小限。必要な場合は `{{- if .Values.<feature>.enabled }}` パターン:

```yaml
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
...
{{- end }}
```

トップレベルの `enabled` フラグで on/off を制御し、複雑な分岐は避ける。
