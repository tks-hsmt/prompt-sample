# レビューモード

Helm chart をレビューする場合の手順。

## ヒアリング

以下がユーザーの依頼から読み取れない場合、作業に着手せず確認する。

**必須（不明なら必ず確認）:**
- **対象チャート**: どのチャートをレビューするか（パスが明確でなければ確認）

**任意（依頼に含まれていなければ全項目チェックで進める。ただし確認した方がよい場合もある）:**
- **レビュースコープ**: 全項目チェックか、特定の観点（セキュリティのみ、values設計のみ等）に絞るか
- **チャートの用途**: 社内利用か公開か、開発段階か本番間近か（推奨項目の優先度判断に影響する）

## 手順

1. 下記チェックリストに基づいて問題を洗い出す
2. 各指摘に「必須」か「推奨」かを明示する
3. 修正例を具体的に示す
4. セキュリティ上のリスクがある項目は優先度を上げて報告する

## 必須チェックリスト

以下は必ず満たすべき項目。レビュー時はこれらを優先的に確認する。

### 構造・命名
- チャート名: 小文字英字+数字+ハイフンのみ、英字始まり
- `Chart.yaml` の `version`: SemVer 2 (MAJOR.MINOR.PATCH)
- YAML: 2スペースインデント、タブ禁止

### values.yaml
- 変数名: camelCase（小文字始まり）
- 文字列はすべてクォートする（型の明示）
- 各パラメータにパラメータ名で始まるコメント
- 環境別 values ファイル分離（values-dev.yaml, values-production.yaml 等）
- 追加フラグなしで `helm install` できる合理的なデフォルト値

### テンプレート
- 1リソース1ファイル、ファイル名に kind を反映（例: `foo-deployment.yaml`）
- 定義テンプレートはチャート名でプレフィックス（例: `{{ define "myapp.fullname" }}`）
- テンプレート内で `namespace` をハードコードしない
- テンプレートディレクティブのブレース前後にスペース（`{{ .foo }}` not `{{.foo}}`）

### コンテナイメージ
- `latest` 等のフローティングタグ禁止、固定タグまたは SHA ダイジェスト
- `image.repository` / `image.tag` / `image.pullPolicy` を values で分離

### セキュリティ（securityContext）
- `runAsNonRoot: true`
- `runAsUser` / `runAsGroup` / `fsGroup` の明示指定
- `allowPrivilegeEscalation: false`
- `capabilities.drop: ["ALL"]`
- Pod/Container の securityContext を values でオーバーライド可能にする

### リソース・ヘルスチェック
- すべてのコンテナに `resources.requests` / `resources.limits` を設定
- `livenessProbe` と `readinessProbe` を定義

### ラベル
- `app.kubernetes.io/*` 推奨ラベルを使用
- `selector.matchLabels` には不変ラベルのみ（`name` と `instance`）

### 依存関係
- オプショナル依存には `condition` または `tags` を設定

### 運用
- デプロイには `helm upgrade --install` を使用
- 本番では `--atomic` フラグ必須

## 推奨チェックリスト

必須ではないが、品質向上のために推奨する項目。

- `values.schema.json` による入力バリデーション
- フラット構造の values を優先（ネストは関連変数が多い場合のみ）
- `--set` フレンドリーな設計（配列よりマップ）
- `readOnlyRootFilesystem: true`（書き込み先は emptyDir でマウント）
- `seccompProfile.type: RuntimeDefault`
- `automountServiceAccountToken: false`（API 不要時）
- NetworkPolicy テンプレートの組み込み
- `startupProbe`（起動の遅いアプリ）
- 依存チャートのバージョン範囲指定（`~1.2.3`）
- `--timeout`, `--history-max`, `--description` の設定
- CI パイプラインで lint -> template -> dry-run の段階的検証
- helm-docs による README 自動生成
- OCI レジストリでのチャート配布
- Helmfile（10以上のリリース管理時）

## 詳細リファレンス

指摘事項の根拠や具体的な設定パターンを確認したい場合:

| トピック | 参照ファイル |
|---|---|
| 命名規則、バージョニング | `chart-structure.md` |
| values 設計、スキーマ | `values.md` |
| テンプレート構造 | `templates.md` |
| 依存関係、CRD | `dependencies.md` |
| セキュリティ全般 | `security.md` |
| イメージ、リソース、プローブ、ラベル | `workloads.md` |
| 運用、CI/CD、テスト | `operations.md` |
| OCI、Helmfile、ArgoCD、ドキュメント | `ecosystem.md` |
