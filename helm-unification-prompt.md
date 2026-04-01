# GitHub Copilot Agent 向けプロンプト：Helm構成の比較・統一化

> **使い方**: 以下のプロンプトを GitHub Copilot のエージェントモード（Agent Mode）に貼り付けて実行してください。  
> `{PROJECT_A_PATH}` と `{PROJECT_B_PATH}` は実際のフォルダパスに置き換えてください。  
> `{構成要件A}` と `{構成要件B}` にはそれぞれのプロジェクト固有の要件を記載してください。

---

## プロンプト本文

```
あなたはKubernetes/Helmのインフラアーキテクトです。
以下の指示に従い、2つのプロジェクトのHelm構成を比較・分析し、ベストプラクティスに基づいた統一構成案を提案してください。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Step 1: 並行調査
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

以下の2つの調査を同時に行ってください。

## 調査A: 両プロジェクトのHelm構成読み込み

### プロジェクトA: {PROJECT_A_PATH}
### プロジェクトB: {PROJECT_B_PATH}

各プロジェクトについて、以下の観点でファイルツリーと内容を読み込み、分析結果を表にまとめてください。

| 分析観点 | 確認内容 |
|---------|---------|
| ディレクトリ構造 | Chart.yaml / values.yaml / templates/ / charts/ / .helmignore の配置 |
| Chart.yaml | apiVersion, name, version, appVersion, dependencies の定義方法 |
| values.yaml | 値の命名規則（camelCase vs snake_case）、ネスト深度、環境分離方法 |
| テンプレート構成 | _helpers.tpl の活用状況、テンプレートの粒度と分割方針 |
| 環境管理 | 環境別values（dev/stg/prod）の管理方法、helmfile利用有無 |
| ラベル・アノテーション | Kubernetes推奨ラベル (app.kubernetes.io/*) の使用状況 |
| セキュリティ | securityContext, RBAC, ServiceAccount の定義有無 |
| リソース管理 | resources (requests/limits) の定義方針 |
| テスト | templates/tests/ 配下のテスト有無 |
| Secrets管理 | Secret の管理方法（helm-secrets, External Secrets, sealed-secrets 等） |
| CRD | crds/ ディレクトリの有無と使い方 |
| NOTES.txt | インストール後の案内テンプレートの有無 |
| values.schema.json | バリデーションスキーマの有無 |

## 調査B: Helmベストプラクティス（参考情報を以下に提供）

以下のベストプラクティスを統一構成案の策定基準として使用してください。

### B-1. Helm公式ベストプラクティス（https://helm.sh/docs/chart_best_practices/）
- Chart名: 小文字英数字とハイフンのみ。ディレクトリ名 = Chart名
- バージョン: SemVer 2 準拠
- values.yaml: 変数名は camelCase、フラットな構造を推奨（ネストが深いと存在チェックが複雑化）
- テンプレート: `helm create` で生成されるテンプレート名の規約に従う。インデントは2スペース
- イメージタグ: latest / head / canary 等の浮動タグを禁止、固定タグまたはSHAを使用
- ラベル: `app.kubernetes.io/name`, `app.kubernetes.io/instance`, `helm.sh/chart` 等の標準ラベルを使用
- RBAC: ServiceAccountを分離し、必要最小権限を付与

### B-2. チャート標準ディレクトリ構造（https://helm.sh/docs/topics/charts/）
```
mychart/
├── Chart.yaml          # 必須: チャートのメタデータ
├── Chart.lock          # 依存関係のロックファイル
├── values.yaml         # デフォルト設定値
├── values.schema.json  # 推奨: valuesのJSONスキーマ
├── charts/             # 依存チャート
├── crds/               # CRD定義（テンプレート不可）
├── templates/          # テンプレートディレクトリ
│   ├── NOTES.txt       # インストール後案内
│   ├── _helpers.tpl    # 共通ヘルパー
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── hpa.yaml
│   ├── serviceaccount.yaml
│   └── tests/          # テスト定義
│       └── test-connection.yaml
├── .helmignore         # パッケージ除外ファイル
├── LICENSE             # ライセンス
└── README.md           # ドキュメント
```

### B-3. 環境別values管理パターン（複数情報源から総合）
**方法1: helmfile + 環境別valuesファイル**
```
helmfile.yaml
environments/
├── development/
│   └── values.yaml
├── staging/
│   └── values.yaml
└── production/
    └── values.yaml
values/
├── <chart-name>/
│   ├── common.yaml        # 全環境共通
│   ├── development.yaml   # dev固有
│   ├── staging.yaml
│   └── production.yaml
```

**方法2: Helm単体 + -f オプション**
```
chart/
├── values.yaml              # デフォルト（共通）
├── values-dev.yaml          # dev差分
├── values-stg.yaml          # stg差分
└── values-prod.yaml         # prod差分
```

### B-4. セキュリティベストプラクティス（https://techdocs.broadcom.com/ Bitnami記事より）
- 非rootコンテナ: securityContext で runAsUser / fsGroup を設定
- Pod Security Standards への準拠
- イメージの脆弱性スキャン（Trivy / Checkov）

### B-5. テスト・品質管理（https://github.com/andredesousa/helm-best-practices）
- `helm test <release>` でデプロイ後テスト
- helm-unittest によるBDDスタイルのユニットテスト
- helm-docs によるREADME自動生成
- helm-lint でテンプレートの構文チェック
- チャートへのPGP署名（`helm package --sign`）

### B-6. 共通チャート（Library Chart）パターン
- 複数サービスで共通のリソース（ConfigMap, Secret等）は共有Library Chartとして切り出し
- サービスごとに独立したチャートを作成し、共通チャートをdependencyとして参照

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Step 2: 統一構成案の策定
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 1の調査結果を踏まえ、以下のフォーマットで統一構成案を出力してください。

## 出力フォーマット

### 2-1. 差分比較表

| 比較項目 | プロジェクトA（現状） | プロジェクトB（現状） | 統一後の推奨構成 | 変更理由・根拠 |
|---------|-------------------|-------------------|----------------|-------------|
| ディレクトリ構造 | ... | ... | ... | 根拠: B-2 (Helm公式) |
| values命名規則 | ... | ... | ... | 根拠: B-1 (公式BP) |
| ... | ... | ... | ... | ... |

### 2-2. 統一後のディレクトリ構造（ツリー表示）

両プロジェクトに共通適用する統一ディレクトリ構造をツリーで提示してください。

### 2-3. 改善提案リスト

Step 1の調査で見つかった問題点・改善点を優先度付きで一覧化してください。

| # | 優先度 | 対象 | 改善内容 | 根拠（Step1調査Bのセクション番号） |
|---|-------|------|---------|-------------------------------|
| 1 | 高 | 両方 | ... | B-1: values命名規則 |
| 2 | 中 | PJ-A | ... | B-4: セキュリティ |
| ... | ... | ... | ... | ... |

### 2-4. 移行手順

統一構成へ移行するためのステップを記載してください。
破壊的変更がある場合は明示してください。

## 制約条件（必ず遵守）

1. **構成要件の維持**: 以下に記載する各プロジェクトの構成要件から逸脱しないこと
   - プロジェクトA の構成要件: {構成要件A}
   - プロジェクトB の構成要件: {構成要件B}
2. **現状を無条件に正とみなさない**: 現状の設定に問題がある場合は、上記ベストプラクティス（B-1〜B-6）の該当セクションを根拠として改善提案すること
3. **既存の動作を壊さない**: 統一化により既存のデプロイパイプラインやCI/CDが破壊されないよう、移行手順に注意点を含めること
4. **DRYの原則**: 両プロジェクトで重複する定義（共通ラベル、共通ヘルパー等）はLibrary Chart化または共通テンプレートとして統合すること
```

---

## プロンプトのカスタマイズ箇所

| プレースホルダ | 説明 | 記入例 |
|-------------|------|-------|
| `{PROJECT_A_PATH}` | プロジェクトAのHelmフォルダパス | `./services/api/helm` |
| `{PROJECT_B_PATH}` | プロジェクトBのHelmフォルダパス | `./services/web/helm` |
| `{構成要件A}` | プロジェクトA固有の要件 | `EKS上のSpring Bootアプリ。Deployment + Service + Ingress + HPA。環境はdev/stg/prodの3面。helmfileで管理` |
| `{構成要件B}` | プロジェクトB固有の要件 | `EKS上のNext.jsフロントエンド。Deployment + Service + Ingress。環境はdev/prodの2面。helm install -f で管理` |

## ベストプラクティス参考リンク一覧

- Helm公式ベストプラクティス: https://helm.sh/docs/chart_best_practices/
- Helm公式チャート構造: https://helm.sh/docs/topics/charts/
- Helm公式テンプレートBP: https://helm.sh/docs/chart_best_practices/templates/
- Helmチャート2026年ガイド: https://atmosly.com/knowledge/helm-charts-in-kubernetes-definitive-guide-for-2025
- Helm開発者視点のベストプラクティス: https://carlosneto.dev/blog/2025/2025-02-25-helm-best-practices/
- Helmベストプラクティス集（GitHub）: https://github.com/andredesousa/helm-best-practices
- Bitnami本番向けチャートガイド: https://techdocs.broadcom.com/us/en/vmware-tanzu/bitnami-secure-images/bitnami-secure-images/services/bsi-doc/apps-tutorials-production-ready-charts-index.html
- Helmfile ベストプラクティス: https://helmfile.readthedocs.io/en/latest/writing-helmfile/
- Helmfile環境管理ガイド: https://oneuptime.com/blog/post/2026-01-30-helmfile-environments/view
- Codefreshによる Helm BP: https://codefresh.io/docs/docs/ci-cd-guides/helm-best-practices/
- Helm Chart Essentials (DEV Community): https://dev.to/hkhelil/helm-chart-essentials-writing-effective-charts-11ca
- Kubernetes Helm完全ガイド 2026: https://devtoolbox.dedyn.io/blog/kubernetes-helm-complete-guide
