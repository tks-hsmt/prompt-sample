# Helm による Kubernetes デプロイ構成のベストプラクティス（2026年4月時点）

> 本ドキュメントは、Helm v4 系（v4.0.0 GA〜v4.2.0）および Helm v3 後期を対象に、2026年4月時点で確認可能な公式ドキュメント・実績あるブログ記事を根拠として、各ベストプラクティスを「項目→目的→具体的な設定→効果→ユースケース→根拠URL」の構造で記述したものです。

---

## 1. チャートの基本構造と命名規則

### 1.1 チャート名の命名規則

**設定内容**: チャート名は小文字英字で始め、小文字英字・数字・ハイフンのみを使用する。アンダースコア・ドット・大文字は使用しない。チャートを格納するディレクトリ名はチャート名と一致させる。

**目的と効果**: Helm のテンプレートエンジンはハイフン以外の区切り文字で問題を起こす可能性があるため、命名規則を統一することで、チャートリポジトリ全体での一貫性を保ち、チーム内外でのチャート検索・共有を容易にする。ディレクトリ名の一致は Helm のパッケージングフォーマットの要件でもある。

**ユースケース**: パブリックチャートリポジトリへの公開、社内チャートリポジトリの標準化、CI/CDパイプラインでのチャート名自動解決。

**根拠**:
- Helm 公式 Best Practices - General Conventions（https://helm.sh/docs/chart_best_practices/conventions）: チャート名に小文字と数字を使い先頭は英字とする規則、ディレクトリ名がチャート名と一致しなければならない要件が記載されている。

### 1.2 SemVer 2 によるバージョニング

**設定内容**: `Chart.yaml` の `version` フィールドには SemVer 2（MAJOR.MINOR.PATCH）を使用する。後方互換性を壊す変更は MAJOR、機能追加は MINOR、バグ修正は PATCH をインクリメントする。

**目的と効果**: チャート利用者がバージョン番号だけでアップグレードの影響範囲を判断でき、依存関係の解決時にも `^` や `~` 等の範囲指定が正しく機能する。CI/CDでの自動アップグレード判定にも利用可能。

**ユースケース**: 依存チャートの自動更新ポリシー設定（例: `version: "^12.0.0"` で12.x系の最新に追従）。

**根拠**:
- Helm 公式 Best Practices - General Conventions（https://helm.sh/docs/chart_best_practices/conventions）: SemVer 2 の使用が推奨されている。
- Broadcom (Bitnami): Best Practices for Securing and Hardening Helm Charts（https://techdocs.broadcom.com/us/en/vmware-tanzu/bitnami-secure-images/bitnami-secure-images/services/bsi-doc/apps-tutorials-best-practices-hardening-charts-index.html）: MAJOR/MINOR/PATCH の判定基準と、MAJOR変更時のREADMEでのアップグレードパス文書化について記述されている。

### 1.3 `helm create` によるスキャフォールド活用

**設定内容**: 新規チャートは `helm create <chart-name>` で生成し、生成されたテンプレート構造（deployment.yaml, service.yaml, ingress.yaml, hpa.yaml, serviceaccount.yaml, _helpers.tpl, NOTES.txt, tests/）をベースに開発を始める。

**目的と効果**: ゼロからYAMLを手書きする場合に比べ、ベストプラクティスに沿った構造が初期状態で得られる。_helpers.tpl にはフルネーム生成やラベル生成のヘルパーテンプレートが含まれ、重複コードを排除できる。

**根拠**:
- GitHub: andredesousa/helm-best-practices（https://github.com/andredesousa/helm-best-practices）: Kubernetesドキュメントからマニフェストをコピーして手作業でチャートを作成するアプローチはエラーを招きやすいと指摘し、`helm create` の活用を推奨している。
- DevToolbox: Kubernetes Helm: The Complete Guide for 2026（https://devtoolbox.dedyn.io/blog/kubernetes-helm-complete-guide）: `helm create` コマンドがベストプラクティスに沿ったテンプレートを生成する旨が記述されている。

---

## 2. values.yaml の設計と環境分離

### 2.1 テンプレートと設定値の責務分離

**設定内容**: テンプレートファイルにはアプリケーション構造（Kubernetes リソースの定義構造）のみを記述し、環境によって変動しうる値（レプリカ数、イメージタグ、リソースリミット、外部ホスト名等）はすべて `values.yaml` で管理する。テンプレート内にハードコードしない。

**目的と効果**: 同一チャートを dev/staging/production のすべての環境で再利用でき、環境差異を values ファイルのみで管理できる。テンプレートの変更頻度が下がり、テストとレビューの負荷が軽減される。

**根拠**:
- Atmosly: Helm Charts in Kubernetes - Definitive Guide（https://atmosly.com/knowledge/helm-charts-in-kubernetes-definitive-guide-for-2025）: 「Templates should describe structure, not environment specific behavior. Any value that may change between environments should live in values.yaml, not inside templates.」（テンプレートは構造を記述すべきであり、環境固有の動作を記述すべきではない。環境間で変動しうる値はすべてテンプレート内ではなく values.yaml に置くべきである。）と記述されている。
- Helm 公式 Best Practices - Values（https://helm.sh/docs/chart_best_practices/values）: values の命名規則・構造化・型安全性についてのガイドラインが記載されている。

### 2.2 環境別 values ファイルの分離

**設定内容**: `values-dev.yaml`、`values-staging.yaml`、`values-production.yaml` のように環境ごとのファイルを用意し、`helm install -f values-production.yaml` で指定する。共通設定はデフォルトの `values.yaml` に定義する。

**目的と効果**: 環境間の設定ドリフトを防止する。各環境の設定差分が明確になり、コードレビューで変更の影響範囲を判断しやすくなる。

**ユースケース**: 開発環境では `replicaCount: 1`, `resources.limits.cpu: 200m` とし、本番では `replicaCount: 3`, `resources.limits.cpu: 1000m` とする場合に、テンプレートの変更なしで対応可能。

**根拠**:
- Atmosly: Helm Chart Best Practices（https://atmosly.com/knowledge/helm-chart-best-practices-what-every-devops-engineer-should-know）: 同一チャートをすべての環境で再利用し、環境ごとに異なる values ファイルを使うことが推奨されている。
- Atmosly: Helm Charts for Kubernetes Design Patterns（https://atmosly.com/knowledge/helm-charts-for-kubernetes-design-patterns-that-prevent-deployment-chaos）: テンプレートと環境固有設定の分離パターンが解説されており、このパターンにより環境ドリフトが防止できるとしている。

### 2.3 合理的なデフォルト値の提供

**設定内容**: `values.yaml` に合理的なデフォルト値を定義し、追加オプションなしの `helm install myapp ./chart` でもチャートが正常にインストールできる状態にする。

**目的と効果**: 初回利用のハードルを下げ、必要な設定だけをオーバーライドすればよい体験を提供する。不適切なデフォルト（例: リソースリミット未設定）によるインシデントを防止する。

**根拠**:
- DevToolbox: Helm Charts: The Complete Guide for 2026（https://devtoolbox.dedyn.io/blog/helm-charts-complete-guide）: 「Provide sensible defaults — the chart should install with just helm install myapp ./chart and no extra flags」（合理的なデフォルト値を提供すること — チャートは追加フラグなしの helm install myapp ./chart だけでインストールできるべきである。）と記述されている。

### 2.4 変数の命名規則（camelCase）

**設定内容**: values の変数名は小文字で始め、単語の区切りには camelCase を使用する。ハイフン・大文字開始は使用しない。

正しい例: `chickenNoodleSoup: true`
誤った例: `Chicken: true`（組み込み変数と衝突の可能性）、`chicken-noodle-soup: true`（ハイフンは不可）

**目的と効果**: Helm の組み込み変数（`.Release.Name`, `.Capabilities.KubeVersion` 等）はすべて大文字始まりであるため、ユーザー定義の値を小文字始まりにすることで区別が容易になる。ハイフン付き変数名はGoテンプレート内で問題を起こす場合がある。

**根拠**:
- Helm 公式 Best Practices - Values（https://helm.sh/docs/chart_best_practices/values）: 「Variable names should begin with a lowercase letter, and words should be separated with camelcase」（変数名は小文字で始め、単語の区切りにはキャメルケースを使うべきである）と記述されている。

### 2.5 フラット構造 vs ネスト構造

**設定内容**: 大半のケースではフラットな values 構造を優先する。ネストは関連する変数が多数あり、かつ少なくとも1つが必須の場合にのみ使用する。

フラット（推奨）: `serverName: nginx` / `serverPort: 80`
ネスト: `server.name: nginx` / `server.port: 80`

**目的と効果**: フラット構造ではテンプレート内での存在チェックが不要になり、`{{ default "none" .Values.serverName }}` のように簡潔に書ける。ネスト構造では各階層で存在チェックが必要（`{{ if .Values.server }} {{ .Values.server.name }} {{ end }}`）になり、テンプレートが複雑化する。

**根拠**:
- Helm 公式 Best Practices - Values（https://helm.sh/docs/chart_best_practices/values）: 「In most cases, flat should be favored over nested. The reason for this is that it is simpler for template developers and users.」（大半のケースでは、フラット構造がネスト構造より優先されるべきである。理由は、テンプレート開発者とユーザーにとってよりシンプルだからである。）と記述されている。

### 2.6 型の明示（文字列のクォート）

**設定内容**: YAML の型変換の曖昧さを避けるため、文字列はすべてクォートする。整数はテンプレート内で `{{ int $value }}` で変換する。

**目的と効果**: `foo: false` と `foo: "false"` は異なる型として解釈される。大きな整数（`12345678`）は科学記数法に変換される場合がある。これらの予期しない型変換によるバグを防止する。

**根拠**:
- Helm 公式 Best Practices - Values（https://helm.sh/docs/chart_best_practices/values）: 「The easiest way to avoid type conversion errors is to be explicit about strings, and implicit about everything else. Or, in short, quote all strings.」（型変換エラーを避ける最も簡単な方法は、文字列を明示的にし、それ以外は暗黙的にすることである。つまり、すべての文字列をクォートすること。）と記述されている。

### 2.7 `--set` フレンドリーな設計

**設定内容**: values の構造は `--set` フラグでの指定が容易になるよう、リスト（配列）よりもマップ（辞書）を使用する。

使いにくい例:
```yaml
servers:
  - name: foo
    port: 80
```
（`--set servers[0].port=80` のようにインデックス指定が必要で、順序変更に脆弱）

使いやすい例:
```yaml
servers:
  foo:
    port: 80
```
（`--set servers.foo.port=80` で直感的にアクセス可能）

**根拠**:
- Helm 公式 Best Practices - Values（https://helm.sh/docs/chart_best_practices/values）: 配列形式は `--set` での指定が困難であり、順序変更に脆弱であるため、マップ形式が推奨されている。

### 2.8 values.yaml のコメント規則

**設定内容**: `values.yaml` で定義されるすべてのプロパティにコメントを付与する。コメントは対象パラメータ名で始め、少なくとも1文の説明を記述する。

正しい例:
```yaml
# serverHost is the host name for the webserver
serverHost: example
# serverPort is the HTTP listener port for the webserver
serverPort: 9191
```

**目的と効果**: パラメータ名で始めることで grep による検索が容易になり、helm-docs 等のドキュメント生成ツールがパラメータと説明を正確に関連付けられるようになる。

**根拠**:
- Helm 公式 Best Practices - Values（https://helm.sh/docs/chart_best_practices/values）: 「Beginning each comment with the name of the parameter it documents makes it easy to grep out documentation, and will enable documentation tools to reliably correlate doc strings with the parameters they describe.」（各コメントをそれが説明するパラメータ名で始めることで、ドキュメントの grep 検索が容易になり、ドキュメント生成ツールがドキュメント文字列とパラメータを正確に関連付けられるようになる。）と記述されている。

---

## 3. テンプレートの構造とフォーマット

### 3.1 templates/ ディレクトリの構造規則

**設定内容**:
- YAML 出力を生成するテンプレートファイルの拡張子は `.yaml` とする。フォーマット済みコンテンツを生成しないテンプレートには `.tpl` を使用する。
- テンプレートファイル名はダッシュ区切り表記（`my-example-configmap.yaml`）とし、camelCase は使用しない。
- 各リソース定義は独自のテンプレートファイルに配置する。
- テンプレートファイル名はリソースの kind を反映する（例: `foo-pod.yaml`, `bar-svc.yaml`）。

**目的と効果**: ファイル名からリソースの種類を即座に判別でき、チャートの見通しが良くなる。1ファイル1リソースの原則により、個別リソースの変更・レビューが容易になる。

**根拠**:
- Helm 公式 Best Practices - Templates（https://helm.sh/docs/chart_best_practices/templates）: テンプレートファイルの拡張子、命名規則、1リソース1ファイルの原則が記述されている。

### 3.2 定義テンプレートの名前空間化

**設定内容**: `{{ define }}` で作成するテンプレートには、チャート名をプレフィックスとして付ける。

正しい例: `{{- define "nginx.fullname" }}`
誤った例: `{{- define "fullname" }}`

**目的と効果**: 定義テンプレートはグローバルにアクセス可能であり、サブチャートを含むすべてのチャートで共有される。名前空間化しない場合、同名のテンプレートが衝突し、予期しないオーバーライドが発生する。

**根拠**:
- Helm 公式 Best Practices - Templates（https://helm.sh/docs/chart_best_practices/templates）: 「Defined templates (templates created inside a {{ define }} directive) are globally accessible. That means that a chart and all of its subcharts will have access to all of the templates created with {{ define }}. For that reason, all defined template names should be namespaced.」（{{ define }} で作成された定義テンプレートはグローバルにアクセス可能である。チャートとそのすべてのサブチャートが、{{ define }} で作成されたすべてのテンプレートにアクセスできる。そのため、すべての定義テンプレート名は名前空間化されるべきである。）と記述されている。

### 3.3 YAML フォーマット規則

**設定内容**: YAMLファイルは2スペースでインデントする（タブは使用しない）。テンプレートディレクティブの開始ブレースの後と終了ブレースの前にはスペースを入れる。生成されるテンプレートの空白行は最小限にする。

正しい例: `{{ .foo }}`, `{{ print "foo" }}`, `{{- print "bar" -}}`
誤った例: `{{.foo}}`, `{{print "foo"}}`

**根拠**:
- Helm 公式 Best Practices - General Conventions（https://helm.sh/docs/chart_best_practices/conventions）: 「YAML files should be indented using two spaces (and never tabs).」（YAMLファイルは2スペースでインデントすべきである（タブは使用しない）。）と記述されている。
- Helm 公式 Best Practices - Templates（https://helm.sh/docs/chart_best_practices/templates）: テンプレートディレクティブのフォーマット規則と空白のchomp処理が記述されている。

### 3.4 テンプレート内での namespace 定義の回避

**設定内容**: チャートテンプレートの `metadata` セクションで `namespace` プロパティを定義しない。namespace は `helm install --namespace` フラグで指定する。

**目的と効果**: テンプレートに namespace をハードコードすると、異なる namespace へのデプロイ時にテンプレートの修正が必要になる。Helmはテンプレートをそのまま Kubernetes クライアントに送信するため、namespace の指定はクライアント側（Helm, kubectl, Flux, Spinnaker 等）に委ねるべきである。

**根拠**:
- Helm 公式 Best Practices - General Conventions（https://helm.sh/docs/chart_best_practices/conventions）: 「Avoid defining the namespace property in the metadata section of your chart templates. The namespace to apply rendered templates to should be specified in the call to a Kubernetes client via the flag like --namespace.」（チャートテンプレートの metadata セクションで namespace プロパティを定義することを避けること。レンダリングされたテンプレートに適用する namespace は、--namespace のようなフラグで Kubernetes クライアントの呼び出し時に指定すべきである。）と記述されている。

### 3.5 コメントの使い分け（YAML コメント vs テンプレートコメント）

**設定内容**: テンプレートの機能を説明する場合はテンプレートコメント（`{{- /* ... */ -}}`）を使用する。ユーザーがデバッグ時に確認できるべき情報にはYAMLコメント（`# ...`）を使用する。

**目的と効果**: テンプレートコメントはレンダリング後のマニフェストに残らず、チャート開発者向けの内部ドキュメントとして機能する。YAMLコメントはレンダリング後も残り、`helm install --debug` で確認可能。ただし、`required` 等のテンプレート関数を含む行にYAMLコメント `#` を付けると、値が未設定時にレンダリングエラーが発生する点に注意が必要。

**根拠**:
- Helm 公式 Best Practices - Templates（https://helm.sh/docs/chart_best_practices/templates）: YAMLコメントとテンプレートコメントの使い分けガイドラインと、`required` 関数との組み合わせ時の注意事項が記述されている。

---

## 4. 依存関係（Dependencies）の管理

### 19.1 バージョン範囲指定

**設定内容**: 依存チャートのバージョンは完全固定ではなくバージョン範囲を使用する。推奨デフォルトはパッチレベルマッチ（`~1.2.3`）。

```yaml
# Chart.yaml
dependencies:
  - name: postgresql
    version: "~12.1.5"    # 12.1.5 以上 12.2.0 未満にマッチ
    repository: "https://charts.bitnami.com/bitnami"
    condition: postgresql.enabled
```

**目的と効果**: パッチバージョンの自動追従により、セキュリティ修正やバグ修正を自動的に取り込める。完全固定（`12.1.5`）ではパッチ更新のたびに手動変更が必要になる。

**根拠**:
- Helm 公式 Best Practices - Dependencies（https://helm.sh/docs/chart_best_practices/dependencies）: 「Where possible, use version ranges instead of pinning to an exact version. The suggested default is to use a patch-level version match: version: ~1.2.3」（可能な限り、完全固定ではなくバージョン範囲を使用すること。推奨デフォルトはパッチレベルのバージョンマッチ `~1.2.3` である。）と記述されている。

### 16.2 condition と tags によるオプショナル依存制御

**設定内容**: オプショナルな依存チャートには `condition` または `tags` を設定する。condition の推奨形式は `somechart.enabled` とする。

```yaml
dependencies:
  - name: redis
    version: "~17.3.0"
    repository: "https://charts.bitnami.com/bitnami"
    condition: redis.enabled      # values.yaml で redis.enabled: false にすると無効化
  - name: nginx
    tags:
      - webaccelerator           # 複数チャートを同じタグでグループ化
  - name: memcached
    tags:
      - webaccelerator           # nginx と memcached を一括で有効/無効化
```

**目的と効果**: 依存チャートの有効/無効を values で制御でき、不要なコンポーネントのデプロイを防止する。tags を使えば、関連する複数の依存チャートを1つのスイッチでまとめて制御できる。

**根拠**:
- Helm 公式 Best Practices - Dependencies（https://helm.sh/docs/chart_best_practices/dependencies）: 「Conditions or tags should be added to any dependencies that are optional.」（オプショナルな依存関係には condition または tags を追加すべきである。）と記述されている。

---

## 5. Custom Resource Definitions（CRD）の管理

### 20.1 `crds/` ディレクトリの使用

**設定内容**: チャート内に `crds/` ディレクトリを作成し、CRD の YAML を配置する。CRD はテンプレート化されず、`helm install` 時にリソースより先に自動インストールされる。

**目的と効果**: CRD の宣言はそれを使用するリソースより先に登録されている必要がある。`crds/` ディレクトリに配置することで、Helm がインストール順序を保証する。すでにCRDが存在する場合はスキップされる（警告あり）。

### 8.2 CRD ライフサイクルの制約

**設定内容**: Helm は現時点で CRD のアップグレードや削除をサポートしていない。これは意図しないデータ損失の危険性から、コミュニティ議論の結果として明示的に決定されたものである。

**対応策**: CRD のバージョンアップが必要な場合は、`kubectl apply` で直接 CRD を更新するか、CRD を別チャートに分離して個別管理する。

### 8.3 CRD の別チャート化

**設定内容**: CRD 定義を1つのチャートに、CRD を使用するリソースを別のチャートに分離する。

**目的と効果**: CRD のライフサイクル（インストール・アップグレード・削除）をアプリケーションチャートと独立して管理できる。クラスタ管理者がCRDを管理し、開発者がアプリケーションチャートを管理するといった権限分離にも有効。

**根拠**:
- Helm 公式 Best Practices - Custom Resource Definitions（https://helm.sh/docs/chart_best_practices/custom_resource_definitions）: `crds/` ディレクトリによる方法と別チャート化の2つのアプローチが記述されている。CRD のアップグレード・削除がサポートされない理由として「This was an explicit decision after much community discussion due to the danger for unintentional data loss.」（これは意図しないデータ損失の危険性から、多くのコミュニティ議論を経て明示的に決定されたものである。）と記述されている。

---

## 6. values.schema.json によるバリデーション

### 3.1 JSON Schema の配置と自動検証

**設定内容**: チャートのルートに `values.schema.json` を配置する。Helm は `install`、`upgrade`、`template`、`lint` コマンド実行時にこのスキーマに対して自動的にバリデーションを行い、不正な values を事前に拒否する。

**目的と効果**: デプロイ時に発見される設定ミスを開発段階で検知できる。型の不一致（文字列として渡すべきイメージタグを数値として渡す等）、必須値の欠落、許可値の逸脱をすべてインストール前にブロックする。

**ユースケース**: `image.tag` を数値 `1.5` として渡した場合に文字列 `"1.5"` であるべきだとエラーになる。`image.pullPolicy` を `Never` 以外の不正な値で渡した場合に拒否される。

### 3.2 具体的なスキーマ設計パターン

**設定内容**: 必須チェック（`required`）、型チェック（`type`）、列挙値制約（`enum`）、範囲制約（`minimum`/`maximum`）、パターン制約（`pattern`）を組み合わせて使用する。

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["replicaCount", "image"],
  "properties": {
    "replicaCount": { "type": "integer", "minimum": 1 },
    "image": {
      "type": "object",
      "required": ["repository"],
      "properties": {
        "repository": { "type": "string", "minLength": 1 },
        "tag": { "type": "string" },
        "pullPolicy": {
          "type": "string",
          "enum": ["Always", "IfNotPresent", "Never"]
        }
      }
    }
  }
}
```

**効果**: スキーマ自体がチャートのインターフェースドキュメントとして機能し、IDEのオートコンプリート（VSCode YAML拡張等）にも活用できる。

**根拠**:
- OneUptime: Schema Validation for Helm Charts with values.schema.json（https://oneuptime.com/blog/post/2026-01-17-helm-schema-validation-values/view）: JSON Schema がデプロイ前にエラーを検出し、IDEの補完にも活用でき、チャートのインターフェースをドキュメント化する効果が記述されている。
- DEV Community: Helm Chart Essentials & Writing Effective Charts（https://dev.to/hkhelil/helm-chart-essentials-writing-effective-charts-11ca）: 「Early Catch: Validate charts before deploying to production」（早期検出: 本番デプロイ前にチャートを検証する）「Clear Documentation: The JSON schema itself acts as documentation」（明確なドキュメント: JSON スキーマ自体がドキュメントとして機能する）と記述されている。
- Austin Dewey: Helm Tricks: Input Validation with values.schema.json（https://austindewey.com/2020/06/13/helm-tricks-input-validation-with-values-schema-json/）: `enum` による許可値制限、`minimum` による下限値設定の具体例が記述されている。

---

## 7. コンテナイメージの指定方法

### 19.1 固定タグまたはSHAダイジェストの使用

**設定内容**: `latest`、`head`、`canary` などのフローティングタグを使用せず、固定タグ（例: `1.25.3`）または SHA ダイジェスト（例: `nginx@sha256:abc123...`）を使用する。

**目的と効果**: デプロイの再現性を保証する。同じ values で `helm install` すれば、いつでも同じマニフェストが生成され、同じコンテナイメージが pull される。セキュリティ面では、タグの上書き攻撃（同じタグで異なるイメージを push する攻撃）を SHA ダイジェストで防止できる。

**ユースケース**: CI/CD パイプラインでビルドしたイメージに Git コミット SHA をタグとして付与し、`--set image.tag=$GITHUB_SHA` でデプロイする。本番環境では SHA ダイジェストを使い、タグの可変性リスクを完全に排除する。

**根拠**:
- Helm 公式 Best Practices - Pods and PodTemplates（https://helm.sh/docs/chart_best_practices/pods）: 「A container image should use a fixed tag or the SHA of the image. It should not use the tags latest, head, canary, or other tags that are designed to be "floating".」（コンテナイメージは固定タグまたはイメージのSHAを使用すべきである。latest、head、canary、その他のフローティングを意図したタグは使用すべきではない。）と明記されている。
- OneUptime: How to Create a Helm OCI Registry（https://oneuptime.com/blog/post/2026-01-30-helm-oci-registry/view）: 「Use digests in production. Pin deployments to SHA256 digests instead of mutable tags.」（本番環境ではダイジェストを使用すること。可変タグの代わりに SHA256 ダイジェストでデプロイを固定すること。）と記述されている。

### 16.2 イメージ定義の values 分離

**設定内容**: `image.repository`、`image.tag`、`image.pullPolicy` を個別の values キーとして定義し、テンプレートでは `"{{ .Values.image.repository }}:{{ .Values.image.tag }}"` のように参照する。

**目的と効果**: イメージの差し替え（レジストリ移行、バージョンアップ）をテンプレート変更なしで行える。`pullPolicy` も環境ごとに制御可能にする（開発: `Always`、本番: `IfNotPresent`）。

**根拠**:
- Helm 公式 Best Practices - Pods and PodTemplates（https://helm.sh/docs/chart_best_practices/pods）: イメージとタグを `values.yaml` で定義し、差し替えを容易にするパターンが記述されている。

---

## 8. セキュリティ：securityContext の詳細設定

### 20.1 `runAsNonRoot: true` — 非rootユーザーでの実行

**設定内容**: Pod レベルの `securityContext` に `runAsNonRoot: true` を設定する。

**目的と効果**: コンテナプロセスが root（UID 0）で実行されることを Kubernetes が拒否する。万が一コンテナが侵害された場合でも、root 権限による被害（ホストファイルシステムへのアクセス、カーネル設定の変更等）を防止できる。

**ユースケース**: Web アプリケーション、API サーバー等、root 権限を必要としない大半のワークロード。

**根拠**:
- Kubernetes 公式: Configure a Security Context for a Pod or Container（https://kubernetes.io/docs/tasks/configure-pod-container/security-context/）: `runAsUser` によりPod内の全プロセスが指定UIDで実行される仕組みが記述されている。
- Wiz: Kubernetes Security Context Best Practices（https://www.wiz.io/academy/container-security/kubernetes-security-context-best-practices）: 「Configure your workloads to run as non-root users by setting runAsNonRoot: true」（runAsNonRoot: true を設定して、ワークロードを非rootユーザーで実行するよう構成すること。）と Action step として記述されている。

### 8.2 `runAsUser` / `runAsGroup` / `fsGroup` — UID/GID の明示指定

**設定内容**: `runAsUser: 1000`、`runAsGroup: 1000`、`fsGroup: 1000` のように非root のUID/GIDを明示的に指定する。

**目的と効果**: `runAsNonRoot: true` だけではコンテナイメージの Dockerfile に USER が定義されていない場合にエラーとなるため、明示的に UID を指定することで確実に非root実行を保証する。`fsGroup` はマウントされたボリュームのファイル所有グループを設定し、コンテナユーザーがボリュームに読み書きできるようにする。

**ユースケース**: PersistentVolume を使用するステートフルアプリケーション（データベース、ファイルストレージ等）で、ボリュームの権限を非root ユーザーに合わせる場合。

**根拠**:
- Kubernetes 公式: Configure a Security Context（https://kubernetes.io/docs/tasks/configure-pod-container/security-context/）: `fsGroup` により全プロセスが補助グループに含まれ、マウントされたボリュームの所有権がそのグループに変更される仕組みが記述されている。
- Broadcom (Bitnami): Best Practices for Creating Production-Ready Helm Charts（https://techdocs.broadcom.com/us/en/vmware-tanzu/bitnami-secure-images/bitnami-secure-images/services/bsi-doc/apps-tutorials-production-ready-charts-index.html）: `fsGroup` でマウントされたボリュームの権限を変更し、`runAsUser` でコンテナユーザーを指定するパターンが具体例付きで解説されている。

### 8.3 `allowPrivilegeEscalation: false` — 権限昇格の拒否

**設定内容**: コンテナレベルの `securityContext` に `allowPrivilegeEscalation: false` を設定する。

**目的と効果**: `no_new_privs` フラグがコンテナプロセスに設定され、setuid/setgid バイナリを使った権限昇格が不可能になる。未設定の場合はデフォルトで `true` となり、権限昇格が許可される危険な状態になる。

**ユースケース**: すべてのワークロードに対して設定すべき。Kubernetes Pod Security Standards の "Restricted" プロファイルでは必須要件。

**根拠**:
- Dynatrace: Kubernetes Security Best Practices Part 3: Security Context（https://www.dynatrace.com/news/blog/kubernetes-security-best-practices-security-context/）: 未定義時にデフォルトで `true` になることの問題と、`false` に設定すべき理由が記述されている。
- Atmosly: How to Implement Pod Security Standards in Kubernetes（https://atmosly.com/blog/how-to-implement-pod-security-standards-in-kubernetes-2025）: Restricted プロファイルの必須要件として `allowPrivilegeEscalation: false` が記載されている。

### 8.4 `readOnlyRootFilesystem: true` — 読み取り専用ルートファイルシステム

**設定内容**: コンテナレベルの `securityContext` に `readOnlyRootFilesystem: true` を設定する。書き込みが必要なディレクトリ（`/tmp`、`/var/cache` 等）は `emptyDir` ボリュームで個別にマウントする。

**目的と効果**: 攻撃者がコンテナ内にマルウェアを配置したり、アプリケーションのバイナリを改ざんしたりすることを防止する。コンテナのイミュータビリティを実現し、実行環境の整合性を保証する。

**ユースケース**: 一時ファイルを書き込むアプリケーション（Nginx のキャッシュ、アプリの /tmp 等）には emptyDir を組み合わせる。

```yaml
containers:
  - name: app
    securityContext:
      readOnlyRootFilesystem: true
    volumeMounts:
      - name: tmp
        mountPath: /tmp
      - name: cache
        mountPath: /var/cache/nginx
volumes:
  - name: tmp
    emptyDir: {}
  - name: cache
    emptyDir: {}
```

**根拠**:
- Wiz: Kubernetes Security Context Best Practices（https://www.wiz.io/academy/container-security/kubernetes-security-context-best-practices）: 「Set the root filesystem as read-only to contain security attacks and enforce immutability for applications that don't require root privileges at runtime.」（ルートファイルシステムを読み取り専用に設定し、セキュリティ攻撃を封じ込め、実行時にroot権限を必要としないアプリケーションのイミュータビリティを強制すること。）と記述されている。
- OneUptime: How to Implement Kubernetes Pod Security Contexts Correctly（https://oneuptime.com/blog/post/2026-01-19-kubernetes-pod-security-contexts/view）: `readOnlyRootFilesystem: true` と emptyDir を組み合わせた実装パターンが記述されている。

### 8.5 `capabilities.drop: ["ALL"]` — Linux ケーパビリティの全削除

**設定内容**: コンテナレベルで `capabilities.drop: ["ALL"]` を設定し、必要なケーパビリティだけを `add` で追加する。

**目的と効果**: デフォルトでコンテナに付与される Linux ケーパビリティ（NET_RAW, SETUID, SETGID 等）をすべて除去し、攻撃面を最小化する。1024番以下のポートをバインドする必要がある場合のみ `NET_BIND_SERVICE` を追加する。

**ユースケース**: 大半のアプリケーションは ALL drop で動作する。ネットワーク管理ツール等、特定のケーパビリティが必要な場合のみ最小限を add する。

**根拠**:
- Kubernetes 公式: Pod Security Standards（https://kubernetes.io/docs/concepts/security/pod-security-standards/）: Restricted プロファイルの必須要件として `capabilities.drop: ["ALL"]` が記載されている。
- Support Tools: Kubernetes Pod Security Context Best Practices（https://support.tools/kubernetes-pod-security-context-best-practices/）: ALL drop して必要なケーパビリティのみ add するパターンが記述されている。

### 8.6 `seccompProfile.type: RuntimeDefault` — システムコールフィルタリング

**設定内容**: Pod レベルの `securityContext` に `seccompProfile.type: RuntimeDefault` を設定する。

**目的と効果**: コンテナランタイム（containerd, CRI-O）のデフォルト seccomp プロファイルを適用し、危険なシステムコール（`ptrace`, `mount` 等）をブロックする。

**根拠**:
- Atmosly: How to Implement Pod Security Standards in Kubernetes（https://atmosly.com/blog/how-to-implement-pod-security-standards-in-kubernetes-2025）: Restricted プロファイルの必須要件として `seccompProfile.type: RuntimeDefault` が記載されている。

### 8.7 Helm チャートでの設定パターン

**設定内容**: 上記すべてを values.yaml でオーバーライド可能にする。

```yaml
# values.yaml
podSecurityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
  seccompProfile:
    type: RuntimeDefault

containerSecurityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  runAsUser: 1000
  capabilities:
    drop:
      - ALL
```

**根拠**:
- OneUptime: Securing Helm Charts with Security Contexts and Network Policies（https://oneuptime.com/blog/post/2026-01-17-helm-security-contexts-network-policies/view）: values.yaml で `podSecurityContext` と `containerSecurityContext` を分離して管理し、テンプレート内で `toYaml` で展開するパターンが具体例付きで記述されている。

---

## 9. リソースリミットとヘルスチェック

### 21.1 CPU/メモリの requests と limits

**設定内容**: すべてのコンテナに `resources.requests` と `resources.limits` を明示的に設定する。

```yaml
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 256Mi
```

**目的と効果**: `requests` はスケジューラがPodの配置先ノードを決定する際に使用され、`limits` はコンテナが使用できるリソースの上限を設定する。未設定の場合、1つのPodがノード上の全リソースを消費し、他のPodや noubelet 自体に影響を与えるリソース枯渇状態を引き起こす可能性がある。

**根拠**:
- DevOps Training Institute: 10 Helm Best Practices（https://www.devopstraininginstitute.com/blog/10-helm-best-practices-for-smooth-kubernetes-deployments）: 「Explicitly define CPU and memory requests and limits for every container in your chart to prevent resource exhaustion and node failure.」（リソース枯渇とノード障害を防止するため、チャート内のすべてのコンテナに CPU とメモリの requests と limits を明示的に定義すること。）と記述されている。

### 15.2 liveness / readiness / startup probes

**設定内容**: `livenessProbe`（コンテナの再起動判定）、`readinessProbe`（トラフィック受信判定）、`startupProbe`（起動完了判定）を定義する。

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: http
  initialDelaySeconds: 30
  periodSeconds: 10
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /ready
    port: http
  initialDelaySeconds: 5
  periodSeconds: 5

startupProbe:
  httpGet:
    path: /healthz
    port: http
  failureThreshold: 30
  periodSeconds: 10
```

**目的と効果**: liveness probe の失敗でコンテナが自動再起動され、デッドロック等の状態からの回復が可能になる。readiness probe の失敗で Service のエンドポイントから除外され、ユーザーへのエラー応答が防止される。startup probe は起動が遅いアプリケーション（JVM、大規模DB等）で、liveness probe による早期 kill を防止する。Helm の `--wait` フラグは readiness probe の成功を待つため、probes の定義は `--atomic` や `--wait` と連携してデプロイの成功判定にも直結する。

**根拠**:
- DevOps Training Institute: 10 Helm Best Practices（https://www.devopstraininginstitute.com/blog/10-helm-best-practices-for-smooth-kubernetes-deployments）: 「Always define liveness and readiness probes in your charts to allow Kubernetes and Helm to monitor the health of your pods accurately.」（Kubernetes と Helm がPodの健全性を正確にモニタリングできるよう、チャートには常に liveness probe と readiness probe を定義すること。）と記述されている。

---

## 10. ラベルとアノテーションの標準化

### 19.1 推奨ラベルの使用

**設定内容**: Kubernetes の推奨ラベル（`app.kubernetes.io/*`）を使用する。

| ラベル | 区分 | 用途 |
|---|---|---|
| `app.kubernetes.io/name` | REC | アプリケーション名 |
| `app.kubernetes.io/instance` | REC | リリースインスタンス名 |
| `app.kubernetes.io/version` | REC | アプリケーションバージョン |
| `app.kubernetes.io/component` | OPT | コンポーネント識別 |
| `app.kubernetes.io/part-of` | OPT | 上位アプリケーション名 |
| `app.kubernetes.io/managed-by` | REC | 管理ツール（Helm） |

**根拠**:
- Helm 公式 Best Practices - Labels and Annotations（https://helm.sh/docs/chart_best_practices/labels）: REC（推奨）と OPT（任意）の区分付きで推奨ラベルが定義されている。

### 16.2 セレクターの設計

**設定内容**: `selector.matchLabels` には不変のラベル（`app.kubernetes.io/name` と `app.kubernetes.io/instance`）のみを指定し、`version` やリリース日のように変化するラベルは含めない。

**目的と効果**: Deployment の selector は一度作成すると変更不可（immutable）であるため、変動するラベルを含めるとアップグレード時に「selector does not match」エラーが発生する。

**根拠**:
- Helm 公式 Best Practices - Pods and PodTemplates（https://helm.sh/docs/chart_best_practices/pods）: 「Without this, the entire set of labels is used to select matching pods, and this will break if you use labels that change, like version or release date.」（セレクターを指定しない場合、ラベルの全セットがPodのマッチングに使用され、version やリリース日のような変動するラベルを使用すると壊れる。）と明記されている。

---

## 11. NetworkPolicy の組み込み

### 20.1 デフォルト deny + 明示的 allow パターン

**設定内容**: チャート内に NetworkPolicy テンプレートを含め、`values.yaml` の `networkPolicy.enabled` で有効/無効を制御する。デフォルトで全トラフィックを拒否し、必要な通信のみを許可するホワイトリスト方式を採用する。

```yaml
# values.yaml
networkPolicy:
  enabled: true
  allowSameNamespace: true
```

**目的と効果**: Podへの不正アクセスをネットワークレベルで遮断する。マイクロサービス間の通信経路を明示的に定義でき、攻撃者がコンテナを侵害しても横方向の移動（lateral movement）を制限できる。

**ユースケース**: データベースPodへのアクセスをアプリケーションPodからのみに制限する。外部への通信をHTTPS（443番ポート）のみに制限する。

**根拠**:
- OneUptime: Securing Helm Charts with Security Contexts and Network Policies（https://oneuptime.com/blog/post/2026-01-17-helm-security-contexts-network-policies/view）: deny-all ポリシーと特定通信の許可ポリシーを組み合わせたパターンが、Helmテンプレートの具体例付きで記述されている。

---

## 12. ServiceAccount と automountServiceAccountToken

### 21.1 専用 ServiceAccount の作成

**設定内容**: `serviceAccount.create: true` でチャート専用の ServiceAccount を作成し、`default` ServiceAccount の使用を避ける。

**目的と効果**: `default` ServiceAccount は namespace 内の全 Pod で共有されるため、RBAC で権限を付与すると意図しない Pod にも権限が波及する。専用 ServiceAccount により最小権限原則を実現する。

### 15.2 `automountServiceAccountToken: false`

**設定内容**: Kubernetes API にアクセスする必要がない Pod では `automountServiceAccountToken: false` を設定する。

**目的と効果**: デフォルトでは ServiceAccount のトークンが全 Pod に自動マウントされ、コンテナからKubernetes APIにアクセス可能になる。API アクセスが不要な Pod ではこのトークンのマウントを無効化することで、コンテナ侵害時のAPI経由の攻撃面を排除する。Pod Security Standards の Restricted プロファイルや CIS Kubernetes Benchmark でも推奨されている。

```yaml
# values.yaml
serviceAccount:
  create: true
  name: ""
  automountToken: false
```

**根拠**:
- Kubernetes 公式: Configure Service Accounts for Pods（https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/）: `automountServiceAccountToken: false` によるトークンマウントの無効化方法が記述されている。
- Helm 公式 Best Practices - RBAC（https://helm.sh/docs/chart_best_practices/rbac）: RBAC と ServiceAccount を独立したキーで管理するパターンが記述されている。
- OneUptime: Securing Helm Charts with Security Contexts and Network Policies（https://oneuptime.com/blog/post/2026-01-17-helm-security-contexts-network-policies/view）: `automountToken: false` をデフォルト設定とした values.yaml の具体例が記述されている。

---

## 13. OCI レジストリによるチャート配布

### 19.1 OCI レジストリへの移行

**設定内容**: Helm 3.8+ / Helm 4 で GA の OCI サポートを使用し、`helm push` でECR・GCR・ACR・GHCR等にチャートを格納する。

**目的と効果**: 従来の ChartMuseum（index.yaml ベースの HTTP リポジトリ）に比べ、コンテナイメージとチャートの認証・認可・脆弱性スキャン・アクセスコントロール・レプリケーションを統一基盤で管理できる。`helm repo add` / `helm repo update` が不要になり、ワークフローが簡素化される。

**根拠**:
- Helm 公式ドキュメント: Use OCI-based registries（https://helm.sh/docs/topics/registries/）: OCI レジストリの使用方法が公式に文書化されている。
- Helm 公式ブログ: Storing Helm Charts in OCI（https://helm.sh/blog/storing-charts-in-oci/）: 「Sharing a common storage standard that's not specific to Helm allows greater interoperability between tools from the wider container ecosystem for security, identity and access management, and more.」（Helm に固有でない共通のストレージ標準を共有することで、セキュリティ、アイデンティティおよびアクセス管理などにおいて、より広いコンテナエコシステムのツール間での相互運用性が向上する。）と記述されている。

### 16.2 チャートの署名と検証

**設定内容**: `helm package --sign` でGPG鍵によりチャートに署名し、利用者は `--verify` で検証する。

**目的と効果**: チャートのサプライチェーン攻撃（改ざんされたチャートの配布）を防止する。

**根拠**:
- OneUptime: How to Create a Helm OCI Registry（https://oneuptime.com/blog/post/2026-01-30-helm-oci-registry/view）: 「Sign your charts. Use helm package --sign with GPG keys for supply chain security.」（チャートに署名すること。サプライチェーンセキュリティのために helm package --sign を GPG 鍵とともに使用すること。）と記述されている。

---

## 14. helm upgrade/install の運用パラメータ

### 20.1 `--atomic` フラグ

**設定内容**: `helm upgrade --install --atomic` を使用する。

**目的と効果**: アップグレードが失敗した場合に自動的にロールバックする。`--wait` フラグも暗黙的に有効化され、すべてのPod・PVC・Service がready状態になるまで待機する。初回インストール（`--install` と併用時）で失敗した場合はリリース自体が削除される。これによりリリースが FAILED 状態で放置されることを防止する。

**ユースケース**: CI/CD パイプラインでの本番デプロイ。手動介入なしでの安全なデプロイを実現する。

**根拠**:
- Helm 公式ドキュメント: helm upgrade（https://helm.sh/docs/helm/helm_upgrade/）: 「--atomic: if set, upgrade process rolls back changes made in case of failed upgrade. The --wait flag will be set automatically if --atomic is used」（--atomic: 設定された場合、アップグレード失敗時にアップグレードプロセスが変更をロールバックする。--atomic を使用すると --wait フラグが自動的に設定される。）と記述されている。
- OneUptime: How to Upgrade and Rollback Helm Releases Safely（https://oneuptime.com/blog/post/2026-01-17-helm-upgrade-rollback-releases/view）: 「Always use --atomic and --wait in production」（本番環境では常に --atomic と --wait を使用すること。）と記述されている。

### 20.2 `--timeout` フラグ

**設定内容**: `--timeout 10m` のようにデプロイのタイムアウトを設定する。デフォルトは 5 分。

**目的と効果**: デフォルトの5分では大規模アプリケーション（JVM起動、DB マイグレーション等）で不十分な場合がある。一方で長すぎるとCI/CDパイプラインが不必要にブロックされる。アプリケーションの特性に応じた適切な値を設定する。

**注意点**: このタイムアウトはチャート内の全リソースに対してグローバルに適用され、個別Pod単位のタイムアウトではない。

**根拠**:
- Polar Squad: Check your Helm deployments!（https://polarsquad.com/blog/check-your-helm-deployments）: タイムアウトがチャート全体のリソースに対してグローバルに適用されるため、全Podを考慮した値を設定する必要があると記述されている。

### 17.3 `--history-max` フラグ

**設定内容**: `--history-max 10` のようにリリース履歴の保持数を制限する。

**目的と効果**: Helm はリリースごとにリビジョンを Kubernetes Secret として保存するため、履歴が無制限に蓄積すると etcd のストレージを圧迫する。10〜20 程度に制限することで、ロールバック能力を維持しつつストレージ消費を抑える。

**ユースケース**: 頻繁にデプロイされるアプリケーション（1日に複数回デプロイ）で特に重要。50リリース × 各数百KBのSecretがクラスタ全体で蓄積する問題を防止する。

**根拠**:
- OneUptime: How to Roll Back and Manage Helm Release History（https://oneuptime.com/blog/post/2026-02-20-helm-rollback-history/view）: 各リリースリビジョンが Kubernetes Secret として保存される仕組みと、`--history-max` による制限が記述されている。
- OneUptime: Helm Performance Optimization: Large-Scale Deployments（https://oneuptime.com/blog/post/2026-01-17-helm-performance-optimization-large-scale/view）: リリース履歴管理がパフォーマンス最適化の重要項目として記述されている。

### 14.4 `--cleanup-on-fail` フラグ

**設定内容**: `helm upgrade --cleanup-on-fail` を使用する。

**目的と効果**: アップグレード失敗時に、そのアップグレードで新たに作成されたリソースを削除する。`--atomic` がロールバック（前リビジョンの復元）であるのに対し、`--cleanup-on-fail` はゴミリソースの掃除に特化している。

**根拠**:
- Helm 公式ドキュメント: helm upgrade（https://helm.sh/docs/helm/helm_upgrade/）: 「--cleanup-on-fail: allow deletion of new resources created in this upgrade when upgrade fails」（--cleanup-on-fail: アップグレード失敗時に、このアップグレードで新たに作成されたリソースの削除を許可する。）と記述されている。

### 14.5 `helm upgrade --install`（べき等なデプロイ）

**設定内容**: `helm install` と `helm upgrade` を個別に使い分けるのではなく、常に `helm upgrade --install` を使用する。

**目的と効果**: リリースが存在しない場合はインストール、存在する場合はアップグレードを行い、べき等（idempotent）な操作を実現する。CI/CD パイプラインで「すでにインストール済みかどうか」の条件分岐が不要になる。

**根拠**:
- Coder Society: 13 Best Practices for using Helm（https://codersociety.com/blog/articles/helm-best-practices）: 「Always use the helm upgrade --install command. It installs the charts if they are not already installed. If they are already installed, it upgrades them.」（常に helm upgrade --install コマンドを使用すること。チャートがまだインストールされていなければインストールし、すでにインストールされていればアップグレードする。）と記述されている。

### 14.6 `--description` フラグ

**設定内容**: `helm upgrade --description "Upgrade to fix CVE-2026-1234"` のようにリリースの説明を付与する。

**目的と効果**: `helm history` で各リビジョンの変更理由を確認でき、障害発生時の原因特定やロールバック判断に役立つ。

**根拠**:
- OneUptime: How to Manage Helm Release Versions in Rancher（https://oneuptime.com/blog/post/2026-03-19-rancher-helm-versions/view）: 「Use --description during upgrades to record why changes were made」（アップグレード時に --description を使用して、変更の理由を記録すること。）と記述されている。

---

## 15. CI/CD パイプラインへの統合

### 21.1 段階的バリデーション

**設定内容**: CI パイプラインに以下のステージを必須として構成する。

1. **`helm lint`**: 構文エラー、values.schema.json 違反を検出
2. **`helm template` + kubeconform**: レンダリング結果の Kubernetes API スキーマ検証
3. **`helm install --dry-run=server`**: クラスタ接続を含むサーバーサイドの事前検証
4. **`helm test`**: デプロイ後のスモークテスト

**目的と効果**: 各段階で異なるレイヤーの問題を検出する。`helm lint` はチャート構造の問題、kubeconform は Kubernetes マニフェストの妥当性、dry-run はクラスタ固有の制約（Namespace存在、RBAC権限等）を検証する。

**根拠**:
- Baeldung: How to Validate Helm Chart Content（https://www.baeldung.com/ops/helm-validate-chart-content）: `helm lint`、`helm template`、kubeconform、`values.schema.json` を段階的に活用するバリデーション戦略が解説されている。
- Atmosly: Helm Charts for Kubernetes Design Patterns（https://atmosly.com/knowledge/helm-charts-for-kubernetes-design-patterns-that-prevent-deployment-chaos）: 「Automated validation prevents broken templates from reaching production.」（自動バリデーションにより、壊れたテンプレートが本番環境に到達することを防止する。）と記述されている。

### 15.2 本番デプロイコマンドの推奨構成

```bash
helm upgrade --install my-app ./charts/my-app \
  --namespace production \
  --create-namespace \
  -f values/production.yaml \
  --set image.tag=${GITHUB_SHA} \
  --atomic \
  --timeout 10m \
  --history-max 10 \
  --description "Deploy ${GITHUB_SHA::8} from ${GITHUB_REF_NAME}"
```

各フラグの意味と効果は本ドキュメントの各セクションで説明済み。

---

## 16. シークレット管理

### 19.1 helm-secrets プラグイン + SOPS

**設定内容**: `helm plugin install https://github.com/jkroepke/helm-secrets` でプラグインをインストールし、Mozilla SOPS で values ファイルを暗号化して Git にコミットする。

**目的と効果**: シークレットを Git で管理しつつ、平文での保存を防止する。AWS KMS、GCP KMS、Azure Key Vault、PGP をバックエンドとして利用可能。Helmfileとの統合にも対応しており、`secrets:` ディレクティブで暗号化ファイルを自動復号する。

**根拠**:
- helm-secrets プラグイン（https://github.com/jkroepke/helm-secrets）: Gitワークフローと統合し、SOPS 経由で複数のKMSバックエンドをサポート。
- Sedai: 27 Top Kubernetes Management Tools for 2026（https://sedai.io/blog/a-guide-to-kubernetes-management）: 「Encrypted secret management through plugins such as Helm-Secrets, allowing secure storage and templating of Kubernetes secrets.」（Helm-Secrets 等のプラグインによる暗号化シークレット管理により、Kubernetes シークレットの安全な保存とテンプレート化が可能になる。）と記述されている。

### 16.2 External Secrets Operator / Sealed Secrets

**設定内容**: External Secrets Operator で AWS Secrets Manager / HashiCorp Vault 等から動的にKubernetes Secretを生成する。または Sealed Secrets で kubeseal による暗号化 SealedSecret をGitにコミットする。

**目的と効果**: helm-secrets がデプロイ時に復号するのに対し、External Secrets Operator はクラスタ内のコントローラーが継続的に外部ストアと同期する。シークレットのローテーションにも対応可能。

**根拠**:
- DevToolbox: Kubernetes Helm: The Complete Guide for 2026（https://devtoolbox.dedyn.io/blog/kubernetes-helm-complete-guide）: helm-secrets と External Secrets Operator の両方のアプローチが記述されている。

---

## 17. テストの実装

### 20.1 `helm test` によるスモークテスト

**設定内容**: `templates/tests/` にテスト用Podを配置し、`helm.sh/hook: test` アノテーションを付与する。

**目的と効果**: デプロイ後にアプリケーションが正常に動作していることを自動検証する。テストPodのコンテナが終了コード 0 で終了すれば成功。

### 20.2 helm-unittest による単体テスト

**設定内容**: helm-unittest プラグインでBDDスタイルのユニットテストを作成する。

**目的と効果**: クラスタに接続せずにテンプレートのレンダリング結果を検証できる。特定の values を渡した場合に期待するリソースが生成されるか、条件分岐が正しく動作するかをテストする。

### 17.3 chart-testing（ct）ツール

**設定内容**: `ct lint --charts ./mychart` と `ct install --charts ./mychart` で lint + install テストを自動化する。

**目的と効果**: GitHub Actions の `helm/chart-testing-action` と統合して PR ごとに自動テストを実行できる。

**根拠**:
- DevToolbox: Helm Charts: The Complete Guide for 2026（https://devtoolbox.dedyn.io/blog/helm-charts-complete-guide）: chart-testing（ct）ツールを使った自動テストの方法が記述されている。
- GitHub: andredesousa/helm-best-practices（https://github.com/andredesousa/helm-best-practices）: helm test と helm-unittest の活用が推奨されている。

---

## 18. Helmfile による複数リリース管理

### 21.1 宣言的リリース管理

**設定内容**: `helmfile.yaml` で全リリースの設定を一元管理し、`helmfile diff` で変更差分を確認した上で `helmfile sync` で適用する。

**目的と効果**: 10個以上のリリースを複数環境で管理する場合に、個別の `helm upgrade` コマンドの羅列では管理が破綻する。Helmfile は環境別 values、シークレット統合、リリース間の依存関係、並列デプロイをサポートする。

**根拠**:
- OneUptime: How to Use Helmfile for Declarative Helm Release Management（https://oneuptime.com/blog/post/2026-01-17-helm-helmfile-declarative-releases/view）: Helmfile の環境管理、シークレット統合、リリース依存関係の定義、CI/CDとの統合が記述されている。
- Helmfile 公式ドキュメント: Secrets（https://helmfile.readthedocs.io/en/latest/remote-secrets/）: vals を通じた外部シークレットストアとの連携が記述されている。

---

## 19. GitOps（ArgoCD）との統合

### 19.1 ArgoCD + OCI レジストリ

**設定内容**: ArgoCD Application で `repoURL` に OCI レジストリを指定し、`syncPolicy.automated` で自動同期を有効化する。`selfHeal: true` でクラスタ状態の自動修復、`prune: true` で不要リソースの自動削除を設定する。

**目的と効果**: Git リポジトリを信頼の源泉とし、クラスタ状態の drift を自動検知・修復する。OCI レジストリとの統合により、チャートの配布とデプロイを一気通貫で管理できる。

**根拠**:
- OneUptime: How to implement ArgoCD with OCI registries for Helm chart deployments（https://oneuptime.com/blog/post/2026-02-09-argocd-oci-helm-charts/view）: ArgoCD + OCI の構成が ECR, GCR, ACR, GHCR の認証設定を含めて解説されている。
- Plural: Kubernetes Helm Charts: A Practical Guide（https://www.plural.sh/blog/kubernetes-helm-charts-guide/）: GitOps ワークフローにより一貫性と監査可能性を確保できると記述されている。

---

## 20. ドキュメンテーション

### 20.1 helm-docs による自動生成

**設定内容**: `helm-docs` を使い、`values.yaml` のコメントと `Chart.yaml` から README.md を自動生成する。pre-commit hook と統合して常に最新の状態を維持する。

**目的と効果**: values.yaml への変更がREADMEに自動反映され、ドキュメントの陳腐化を防止する。

### 20.2 NOTES.txt

**設定内容**: `templates/NOTES.txt` にインストール後の手順（アクセスURL取得コマンド、初期パスワード取得方法等）を記述する。

**目的と効果**: `helm install` 完了後に自動表示され、利用者が次のステップを即座に把握できる。

**根拠**:
- DEV Community: Helm Chart Essentials & Writing Effective Charts（https://dev.to/hkhelil/helm-chart-essentials-writing-effective-charts-11ca）: helm-docs の活用と自動ドキュメント生成が記述されている。
- Coder Society: 13 Best Practices for using Helm（https://codersociety.com/blog/articles/helm-best-practices）: Comments、README、NOTES.txt の3つのドキュメント手段が記述されている。

---

## 21. Helm 4 への対応

### 21.1 Server-Side Apply

**設定内容**: Helm 4 は Kubernetes の Server-Side Apply と統合し、フィールドの所有権管理を改善している。

**目的と効果**: Helm 3 の client-side 3-way merge では ArgoCD 等の GitOps ツールとフィールド所有権が競合し、configuration drift が発生することがあった。Server-Side Apply ではフィールドごとの所有者が API サーバー側で管理され、この問題が解消される。

### 21.2 後方互換性

**設定内容**: Helm 4 は v2 API チャート（Helm 3 のチャート）との後方互換性を維持している。

**目的と効果**: 既存のチャートをそのまま Helm 4 で使用でき、段階的な移行が可能。

**根拠**:
- Helm 公式ドキュメント（https://helm.sh/docs/）: 「Helm v4 represents a significant evolution from v3, introducing breaking changes, new architectural patterns, and enhanced functionality while maintaining backwards compatibility for charts.」（Helm v4 は v3 からの重要な進化であり、チャートとの後方互換性を維持しつつ、破壊的変更、新しいアーキテクチャパターン、強化された機能を導入している。）と記述されている。
- Helm 公式サイト（https://helm.sh/）: v4.2.0（2026年5月）リリースが記載されている。

---

## 総合チェックリスト

| カテゴリ | チェック項目 | 必須/推奨 | 公式BP |
|---|---|---|---|
| **構造** | `helm create` ベースで開発 | 推奨 | ✓ |
| **構造** | SemVer 2 バージョニング | 必須 | ✓ |
| **構造** | YAML 2スペースインデント（タブ禁止） | 必須 | ✓ |
| **values** | camelCase 命名規則 | 必須 | ✓ |
| **values** | フラット構造の優先 | 推奨 | ✓ |
| **values** | 文字列のクォート（型の明示） | 必須 | ✓ |
| **values** | `--set` フレンドリーな設計（配列よりMap） | 推奨 | ✓ |
| **values** | パラメータ名で始まるコメント | 必須 | ✓ |
| **values** | 環境別 values ファイル分離 | 必須 | |
| **values** | `values.schema.json` による検証 | 推奨 | |
| **values** | 合理的なデフォルト値の提供 | 必須 | |
| **テンプレート** | 1リソース1ファイル、kind反映ファイル名 | 必須 | ✓ |
| **テンプレート** | 定義テンプレートの名前空間化 | 必須 | ✓ |
| **テンプレート** | ブレース前後のスペース、chomp処理 | 推奨 | ✓ |
| **テンプレート** | namespace プロパティの定義回避 | 必須 | ✓ |
| **テンプレート** | YAML/テンプレートコメントの使い分け | 推奨 | ✓ |
| **依存関係** | バージョン範囲指定（`~1.2.3`） | 推奨 | ✓ |
| **依存関係** | condition/tags によるオプショナル制御 | 必須 | ✓ |
| **CRD** | `crds/` ディレクトリまたは別チャート化 | 必須 | ✓ |
| **イメージ** | 固定タグまたは SHA ダイジェスト | 必須 | ✓ |
| **イメージ** | `image.repository` / `tag` / `pullPolicy` の values 分離 | 必須 | ✓ |
| **セキュリティ** | `runAsNonRoot: true` | 必須 | |
| **セキュリティ** | `runAsUser` / `runAsGroup` / `fsGroup` の明示指定 | 必須 | |
| **セキュリティ** | `allowPrivilegeEscalation: false` | 必須 | |
| **セキュリティ** | `readOnlyRootFilesystem: true` | 推奨 | |
| **セキュリティ** | `capabilities.drop: ["ALL"]` | 必須 | |
| **セキュリティ** | `seccompProfile.type: RuntimeDefault` | 推奨 | |
| **セキュリティ** | `automountServiceAccountToken: false`（API不要時） | 推奨 | |
| **セキュリティ** | NetworkPolicy の組み込み | 推奨 | |
| **リソース** | CPU/メモリの requests/limits 定義 | 必須 | |
| **ヘルスチェック** | liveness / readiness probe 定義 | 必須 | |
| **ヘルスチェック** | startup probe（起動の遅いアプリ） | 推奨 | |
| **ラベル** | `app.kubernetes.io/*` 推奨ラベル使用 | 必須 | ✓ |
| **ラベル** | selector に不変ラベルのみ使用 | 必須 | ✓ |
| **RBAC** | 専用 ServiceAccount の作成 | 推奨 | ✓ |
| **RBAC** | RBAC と ServiceAccount の分離管理 | 必須 | ✓ |
| **配布** | OCI レジストリの使用 | 推奨 | |
| **配布** | チャート署名（`--sign`） | 推奨 | |
| **運用** | `helm upgrade --install` の使用 | 必須 | |
| **運用** | `--atomic` フラグ（本番） | 必須 | |
| **運用** | `--timeout` の明示設定 | 推奨 | |
| **運用** | `--history-max` の制限（10〜20） | 推奨 | |
| **運用** | `--description` によるリビジョン記述 | 推奨 | |
| **CI/CD** | lint → template → dry-run の段階的検証 | 必須 | |
| **CI/CD** | `helm test` によるデプロイ後検証 | 推奨 | |
| **シークレット** | helm-secrets / ESO / Sealed Secrets | 必須 | |
| **管理** | Helmfile（10+リリース時） | 推奨 | |
| **GitOps** | ArgoCD + OCI 統合 | 推奨 | |
| **ドキュメント** | helm-docs による自動生成 | 推奨 | |
| **ドキュメント** | NOTES.txt の提供 | 推奨 | |

> **公式BP列の ✓** は Helm 公式 Best Practices ガイド（https://helm.sh/docs/chart_best_practices/）に記載されている項目を示す。✓ のない項目は業界ベストプラクティスやサードパーティのガイダンスに基づく項目。

---

*最終更新: 2026年4月*
