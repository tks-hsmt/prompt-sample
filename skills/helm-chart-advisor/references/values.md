# values.yaml の設計と環境分離

## テンプレートと設定値の責務分離

**設定内容**: テンプレートファイルにはアプリケーション構造（Kubernetes リソースの定義構造）のみを記述し、環境によって変動しうる値（レプリカ数、イメージタグ、リソースリミット、外部ホスト名等）はすべて `values.yaml` で管理する。テンプレート内にハードコードしない。

## 環境別 values ファイルの分離

**設定内容**: `values-dev.yaml`、`values-staging.yaml`、`values-production.yaml` のように環境ごとのファイルを用意し、`helm install -f values-production.yaml` で指定する。共通設定はデフォルトの `values.yaml` に定義する。

**目的と効果**: 環境間の設定ドリフトを防止する。各環境の設定差分が明確になり、コードレビューで変更の影響範囲を判断しやすくなる。

**ユースケース**: 開発環境では `replicaCount: 1`, `resources.limits.cpu: 200m` とし、本番では `replicaCount: 3`, `resources.limits.cpu: 1000m` とする場合に、テンプレートの変更なしで対応可能。

## 合理的なデフォルト値の提供

**設定内容**: `values.yaml` に合理的なデフォルト値を定義し、追加オプションなしの `helm install myapp ./chart` でもチャートが正常にインストールできる状態にする。

## 変数の命名規則（camelCase）

**設定内容**: values の変数名は小文字で始め、単語の区切りには camelCase を使用する。ハイフン・大文字開始は使用しない。

正しい例: `chickenNoodleSoup: true`
誤った例: `Chicken: true`（組み込み変数と衝突の可能性）、`chicken-noodle-soup: true`（ハイフンは不可）

**目的と効果**: Helm の組み込み変数（`.Release.Name`, `.Capabilities.KubeVersion` 等）はすべて大文字始まりであるため、ユーザー定義の値を小文字始まりにすることで区別が容易になる。

## フラット構造 vs ネスト構造

**設定内容**: 大半のケースではフラットな values 構造を優先する。ネストは関連する変数が多数あり、かつ少なくとも1つが必須の場合にのみ使用する。

フラット（推奨）: `serverName: nginx` / `serverPort: 80`
ネスト: `server.name: nginx` / `server.port: 80`

**目的と効果**: フラット構造ではテンプレート内での存在チェックが不要になり、`{{ default "none" .Values.serverName }}` のように簡潔に書ける。ネスト構造では各階層で存在チェックが必要になり、テンプレートが複雑化する。

## 型の明示（文字列のクォート）

**設定内容**: YAML の型変換の曖昧さを避けるため、文字列はすべてクォートする。整数はテンプレート内で `{{ int $value }}` で変換する。

**目的と効果**: `foo: false` と `foo: "false"` は異なる型として解釈される。大きな整数は科学記数法に変換される場合がある。これらの予期しない型変換によるバグを防止する。

## `--set` フレンドリーな設計

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

## values.yaml のコメント規則

**設定内容**: `values.yaml` で定義されるすべてのプロパティにコメントを付与する。コメントは対象パラメータ名で始め、少なくとも1文の説明を記述する。

正しい例:
```yaml
# serverHost はWebサーバーのホスト名
serverHost: example
# serverPort はWebサーバーのHTTPリスナーポート
serverPort: 9191
```

**目的と効果**: パラメータ名で始めることで grep による検索が容易になり、helm-docs 等のドキュメント生成ツールがパラメータと説明を正確に関連付けられるようになる。

---

# values.schema.json によるバリデーション

## JSON Schema の配置と自動検証

**設定内容**: チャートのルートに `values.schema.json` を配置する。Helm は `install`、`upgrade`、`template`、`lint` コマンド実行時にこのスキーマに対して自動的にバリデーションを行い、不正な values を事前に拒否する。

**目的と効果**: デプロイ時に発見される設定ミスを開発段階で検知できる。型の不一致、必須値の欠落、許可値の逸脱をすべてインストール前にブロックする。

## 具体的なスキーマ設計パターン

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

