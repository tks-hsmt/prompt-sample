# 依存関係（Dependencies）の管理

## バージョン範囲指定

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

## condition と tags によるオプショナル依存制御

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

---

# Custom Resource Definitions（CRD）の管理

## `crds/` ディレクトリの使用

**設定内容**: チャート内に `crds/` ディレクトリを作成し、CRD の YAML を配置する。CRD はテンプレート化されず、`helm install` 時にリソースより先に自動インストールされる。

**目的と効果**: CRD の宣言はそれを使用するリソースより先に登録されている必要がある。`crds/` ディレクトリに配置することで、Helm がインストール順序を保証する。すでにCRDが存在する場合はスキップされる（警告あり）。

## CRD ライフサイクルの制約

**設定内容**: Helm は現時点で CRD のアップグレードや削除をサポートしていない。これは意図しないデータ損失の危険性から、コミュニティ議論の結果として明示的に決定されたものである。

**対応策**: CRD のバージョンアップが必要な場合は、`kubectl apply` で直接 CRD を更新するか、CRD を別チャートに分離して個別管理する。

## CRD の別チャート化

**設定内容**: CRD 定義を1つのチャートに、CRD を使用するリソースを別のチャートに分離する。

**目的と効果**: CRD のライフサイクル（インストール・アップグレード・削除）をアプリケーションチャートと独立して管理できる。クラスタ管理者がCRDを管理し、開発者がアプリケーションチャートを管理するといった権限分離にも有効。

