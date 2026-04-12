# チャートファイル構成ルール

本リファレンスは Helm チャートのディレクトリ構造とファイル配置のルールについて記述します。

---

## ディレクトリ構造

チャートのルート直下の構造は以下に固定する。
```
myapp/
├── .helmignore                     # 必須
├── Chart.yaml                      # 必須
├── values.yaml                     # 必須
├── values.schema.json              # 必須
├── values-dev.yaml                 # 必須
├── values-stg.yaml                 # 必須
├── values-prod.yaml                # 必須
├── README.md                       # 任意
├── README.md.gotmpl                # 任意(helm-docs 導入時)
├── files/                          # 任意(外部設定ファイルがある場合のみ)
├── charts/                         # 任意(サブチャート依存がある場合のみ)
└── templates/                      # 必須
    ├── _helpers.tpl                # 必須
    ├── NOTES.txt                   # 必須
    ├── <workload>.yaml             # 必須(後述)
    ├── serviceaccount.yaml         # 必須
    ├── service.yaml                # 任意
    ├── ingress.yaml                # 任意
    ├── configmap.yaml              # 任意
    ├── hpa.yaml                    # 任意
    ├── pdb.yaml                    # 条件付き必須
    ├── pvc.yaml                    # 任意
    ├── networkpolicy.yaml          # 任意
    ├── role.yaml                   # 条件付き必須
    └── rolebinding.yaml            # 条件付き必須
```

---

## チャート名

チャート名は小文字の英字と数字で構成する。単語はハイフン（-）で区切ることができる。大文字、アンダースコア、ドットは使用しない。

**良い例**:
> aws-cluster-autoscaler

**悪い例**:
> aws_cluster_autoscaler
> aws.cluster.autoscaler
> awsClusterAutoscaler

---

## Chart.yaml の内容ルール

### バージョン番号

`Chart.yaml` のバージョンは **SemVer 2** に厳密に従う。`version` はチャート自身のバージョン、`appVersion` は同梱アプリのバージョンであり、両者は無関係。`appVersion` は YAML パーサーに文字列として扱わせるため必ずクォートする。build metadata(`+xxx`)を使う場合は `version` 側のみに付与し、`appVersion` は Docker tag 互換の素の形に保つ。

**良い例**:
```yaml
apiVersion: v2
name: myapp
type: application
version: 1.4.2
appVersion: "2.7.1"
```

**悪い例**:
```yaml
apiVersion: v2
name: myapp
version: v1.2
appVersion: 1.0
```

理由:
- `v1.2` は先頭 `v` かつ PATCH 欠落で SemVer 2 違反。
- `appVersion: 1.0` はクォートがなく YAML が float として解釈する。git SHA 風の値(例: `1234e10`)では指数表記として誤解釈される危険もある。

### 依存チャートのバージョン指定

再現性は `Chart.lock` で担保し、`dependencies[].version` は完全固定ではなくパッチレベルのレンジで指定する。

**良い例**:
```yaml
dependencies:
  - name: postgresql
    version: ~13.2.24
    repository: https://charts.bitnami.com/bitnami
```

**悪い例**:
```yaml
dependencies:
  - name: postgresql
    version: 13.2.24
    repository: https://charts.bitnami.com/bitnami
```

理由:
- 完全固定するとセキュリティパッチの取り込みが手動更新に依存してしまう。`~13.2.24`(= `>=13.2.24, <13.3.0`)ならパッチには追従しつつマイナー以上の破壊的変更は防げる。

---

## ルート直下の必須ファイル

以下のファイルはチャートルート直下に必ず配置する。**ファイルが存在することを必須とする**。

| ファイル | 役割 |
|---|---|
| `.helmignore` | チャートをパッケージングする際に除外するファイルパターンを記述 |
| `Chart.yaml` | チャートのメタデータ |
| `values.yaml` | デフォルト値定義 |
| `values.schema.json` | values の型とルールを機械的に検証する JSON Schema |
| `values-dev.yaml` | 開発環境のオーバーライド |
| `values-stg.yaml` | ステージング環境のオーバーライド |
| `values-prod.yaml` | 本番環境のオーバーライド |

---

## `templates/` 配下の必須ファイル

### `_helpers.tpl`

共通ヘルパーテンプレートを定義するファイル。**ファイルを必ず配置する**。

### `NOTES.txt`

`helm install` 完了後に表示されるメッセージファイル。**ファイルを必ず配置する**。空ファイルでの提出は禁止する。

### ワークロードテンプレート(いずれか 1 つ必須)

チャートの種類に応じて、以下のいずれか 1 つのワークロードテンプレートを必ず含める。**1 チャートに複数のワークロード種別を混在させない**。

| チャート種別 | 必須ファイル |
|---|---|
| Deployment チャート | `templates/deployment.yaml` |
| StatefulSet チャート | `templates/statefulset.yaml` |
| DaemonSet チャート | `templates/daemonset.yaml` |
| Job チャート | `templates/job.yaml` |
| CronJob チャート | `templates/cronjob.yaml` |

理由:
- 1 チャートに複数ワークロード種別を混在させると、デプロイ単位・ロールバック単位が不明瞭になり、`helm upgrade` の影響範囲が読めなくなる。
- 複数ワークロードを 1 アプリとして管理したい場合は、それぞれ別チャートとして切り出すか、親チャート配下のサブチャートとして構成する。

### `serviceaccount.yaml`

ServiceAccount リソースのテンプレートファイル。`rbac.create` / `serviceAccount.create` の値にかかわらず **ファイル自体は常に配置する**。

理由:
- ファイルの有無でチャートの挙動が変わると、どのチャートに SA が含まれるか/含まれないかをレビュー時に確認する手間が増える。

---

## 任意ファイル(利用場面に応じて追加)

以下のファイルは、該当機能を使う場合にのみテンプレートに追加する。追加した場合は本ルール体系の該当ルールに従うこと。

### `service.yaml`

`Service` リソースを作成する場合に追加する。

Headless Service が追加で必要な場合(StatefulSet 等)は、`service-headless.yaml` として別ファイルを作成する。

### `ingress.yaml`

`Ingress` リソースを作成する場合に追加する。

### `configmap.yaml`

チャートから ConfigMap を生成する場合に追加する。外部から参照する ConfigMap を values の `extraEnvFrom` で指定する場合は、本ファイルは不要。

### `hpa.yaml`

HorizontalPodAutoscaler を作成する場合に追加する。StatefulSet / Deployment 以外のワークロード(Job, CronJob, DaemonSet)では HPA が使えないため、このファイルも追加しない。

### `pvc.yaml`

PersistentVolumeClaim を作成する場合に追加する。StatefulSet では `volumeClaimTemplates` を使うため、`pvc.yaml` は不要。

### `networkpolicy.yaml`

NetworkPolicy を作成する場合に追加する。

---

## 条件付き必須ファイル

以下のファイルは、特定の条件を満たす場合に **必須** となる。

### `pdb.yaml`

Deployment / StatefulSet チャートでは **条件付き必須**。`replicaCount >= 2` のときに PodDisruptionBudget を必須とするため、テンプレートファイルを配置する。

DaemonSet / Job / CronJob チャートでは使用しない(ファイルを配置しない)。

### `role.yaml` / `rolebinding.yaml`

`rbac.create: true` とする場合は `role.yaml` と `rolebinding.yaml` のペアを必須で配置する。**片方だけの配置は禁止する**。

`rbac.create: false` をデフォルトとする通常のチャートでは、ファイル自体を存在させるかどうかはチャート作成者の判断とする。

---

## 外部設定ファイル(`files/` ディレクトリ)

アプリケーションの設定ファイル(`rsyslog.conf`, `nginx.conf`, `fluent.conf`, 初期化 SQL スクリプト、TLS 証明書等)をチャートに同梱する場合は、チャートルート直下の **`files/`** ディレクトリに配置する。

### 配置ルール

- ディレクトリ名は **`files/` に固定** する。`config/` や `conf/` など別名にしてはならない。
- 外部設定ファイルを **`templates/` 配下に置いてはならない**。`templates/` 内のファイルは Helm のテンプレートエンジンを通るため、`.Files.Get` で取得できない。
- 外部設定ファイルを **`charts/` 配下に置いてはならない**。`charts/` はサブチャート依存専用のディレクトリである。
- 1 チャートに 1 コンポーネント分の設定ファイルのみがある場合は、**`files/` 直下に直接配置してよい**。
- 1 チャートに複数コンポーネント分の設定ファイルがある場合は、**コンポーネント別のサブディレクトリ**(`files/rsyslog/`, `files/nginx/` 等)に分けて配置してよい。

**良い例**(1 コンポーネント、`files/` 直下):
```
myapp/
├── files/
│   └── rsyslog.conf
└── templates/
    └── configmap.yaml
```

**良い例**(複数コンポーネント、サブディレクトリで分離):
```
myapp/
├── files/
│   ├── rsyslog/
│   │   └── rsyslog.conf
│   ├── fluentd/
│   │   ├── fluent.conf
│   │   └── parsers.conf
│   └── init-sql/
│       ├── 01-schema.sql
│       └── 02-seed.sql
└── templates/
    └── configmap.yaml
```

**悪い例**:
```
myapp/
├── templates/
│   └── rsyslog.conf        # templates 配下に置いてはならない
├── charts/
│   └── nginx.conf          # charts 配下に置いてはならない
└── config/
    └── fluent.conf         # files/ 以外の名前にしてはならない
```

`files/` 配下のファイルをテンプレート内で読み込む方法(`.Files.Get` / `tpl` / `.Files.Glob` / `b64enc` の使い分け)は **`templates.md`** を参照。

### サイズ制限への注意

`files/` 配下のファイルはすべてチャートパッケージに含まれる。チャート全体のサイズが 1 MiB(etcd の上限)を超えると `helm install` が失敗する。大きなファイル(数百 KB 以上)を `files/` に置く場合は、サイズ合計を意識すること。大容量のデータは ConfigMap / Secret ではなく、PersistentVolume や外部のオブジェクトストレージから読み込む設計に変更する。

---

## 禁止事項

### 許可リストにないファイルの追加

本ルールの「必須」「任意」「条件付き必須」に記載のないファイルをチャートに追加してはならない。

### ClusterRole / ClusterRoleBinding

`clusterrole.yaml` および `clusterrolebinding.yaml` は **通常のチャートでは禁止** する。プラットフォームコンポーネント(オペレータ、コントローラ等)で正当な理由がある場合のみ、本ルール体系の対象外として個別に扱う(詳細は `rbac-basic.md`)。

### 複数リソースを 1 ファイルに詰め込む

1 つのテンプレートファイルには 1 つのリソース定義のみを記述する。複数リソースを 1 ファイルにまとめてはならない(詳細は `templates.md`)。

### `charts/` ディレクトリ(サブチャート依存なし時)

サブチャート依存がないチャートでは `charts/` ディレクトリを作成しない。`helm create` が空ディレクトリを生成するが、依存がないなら削除する。

サブチャート依存がある場合のみ、`Chart.yaml` の `dependencies` セクションに記述し、`helm dependency update` で `charts/` 配下に `.tgz` ファイルが配置される状態とする。

### `files/` ディレクトリの濫用

`files/` はアプリケーションの設定ファイルを置くためのディレクトリであり、以下を置いてはならない。

- ドキュメント類(`README`, `CHANGELOG` 等)
- ビルドスクリプトやテストコード
- 開発時の一時ファイル
- 個人の設定ファイル
