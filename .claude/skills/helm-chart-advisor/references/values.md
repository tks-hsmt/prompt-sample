# Values ルール

本リファレンスでは values.yaml ファイルの値の構成方法と使用方法に関するルールについて記述します。

---
## values.yaml キーの命名規則

values のキーは **小文字始まりの lowerCamelCase とする**。先頭大文字(`UpperCamelCase`)は Helm の組み込み変数(`.Release.Name` など)と衝突する恐れがあるため使用しない。ハイフン区切り・スネークケースは使用しない。

**良い例**:
```yaml
chicken: true
chickenNoodleSoup: true
```

**悪い例**:
```yaml
Chicken: true
chicken-noodle-soup: true
chicken_noodle_soup: true
```

理由:
- `Chicken` のような先頭大文字は Helm 組み込み変数と区別がつかなくなる。
- `chicken-noodle-soup` はテンプレート内で `.Values.chicken-noodle-soup` のドット記法でアクセスできず、`index .Values "chicken-noodle-soup"` を強いられる。
- `chicken_noodle_soup` はチャート命名規則(アンダースコア禁止)と整合させるため不可。

---

## values.yaml のキー構造(フラット / ネスト)

values.yaml は **原則フラット構造とする**。ただし **関連する変数が多数あり、かつそのうち少なくとも 1 つが必須(non-optional)である場合に限り、ネスト構造とする**。ネストの各階層では存在チェックが必要になり、テンプレートが冗長かつ壊れやすくなるため、安易にネストしない。

**良い例**(関連する変数が少ない場合 → フラット):
```yaml
serverName: nginx
serverPort: 80
```
```gotemplate
{{ default "none" .Values.serverName }}
```

**良い例**(関連する変数が多数あり必須項目を含む場合 → ネスト):
```yaml
# image.repository は必須、その他は任意
image:
  repository: ""
  digest: ""
  pullPolicy: IfNotPresent
```

**悪い例**:
```yaml
server:
  name: nginx
  port: 80
```
```gotemplate
{{ if .Values.server }}
  {{ default "none" .Values.server.name }}
{{ end }}
```

理由:
- ネストでは階層ごとに `if .Values.server` のような存在チェックが必要になり、テンプレートが読みづらい。
- フラットなら `{{ default "none" .Values.serverName }}` だけで済む。
- 一方、`image` のように常にひとまとまりで扱う設定群は、フラット化(`imageRepository`, `imageDigest`, `imagePullPolicy`)するとかえって全体像が掴みづらいため、ネストを許容する。

---

## values 標準キー一覧

本セクションは **values.yaml のキーの命名規約（キー名と Kubernetes マニフェスト上のフィールドパスの対応表）** である。

**本セクションの違反判定対象**:
- キー名の命名規約（別名の禁止、キー名と構造の固定）
- 各キーが対応する Kubernetes マニフェストのフィールドパス
- ワークロード種別ごとの適用可否（括弧内の種別表記）

**本セクションで扱わないもの**: キーに入る値の制約（必須性・許容値・禁止値など）。値に関するルールは他リファレンスに帰属する。

チャートが該当する機能を提供する場合、対応する Kubernetes API の階層に合わせて命名・構造化し、**キー名と構造は以下の通りに固定する**。新しいチャートを起こす場合も別名(`additionalEnv`, `commonLabels`, `imageRepository` 等)に変更してはならない。**チャートが使用しない機能のキーは values.yaml に定義しない**。

参照先カラムは **Kubernetes マニフェスト上のフィールドパス** を示す。Helm テンプレート(`spec.template.spec.containers[]` 等)はこの階層と一致させる。

セクション見出しやキーの用途欄に括弧でワークロード種別が記載されている場合、**該当しないワークロードでは values.yaml にそのキーを定義しない**。括弧がないセクション・キーは全ワークロード共通だが、チャートが該当機能を使用しない場合は定義不要である。

### イメージ・レジストリ

| 用途 | キー | テンプレート上の参照箇所 |
|---|---|---|
| イメージリポジトリ | `image.repository` | `spec.template.spec.containers[].image`(repository 部) |
| イメージ digest | `image.digest` | `spec.template.spec.containers[].image`(`@sha256:...` 部) |
| イメージプルポリシー | `image.pullPolicy` | `spec.template.spec.containers[].imagePullPolicy` |
| プライベートレジストリ認証(SA 経由、優先) | `serviceAccount.imagePullSecrets` |
| プライベートレジストリ認証(Pod レベル、例外時のみ) | `imagePullSecrets` |

### 名前・メタデータ

| 用途 | キー | テンプレート上の参照箇所 |
|---|---|---|
| チャート名部分の上書き | `nameOverride` | `metadata.name` 生成ヘルパー(`{{ include "chart.name" . }}`) |
| フルネームの上書き | `fullnameOverride` | `metadata.name` 生成ヘルパー(`{{ include "chart.fullname" . }}`) |
| Pod アノテーション | `podAnnotations` | `spec.template.metadata.annotations` |
| Pod ラベル | `podLabels` | `spec.template.metadata.labels` |
| 全リソース共通ラベル | `extraLabels` | 各リソースの `metadata.labels`(全リソースにマージ) |

### ServiceAccount / RBAC

| 用途 | キー | テンプレート上の参照箇所 |
|---|---|---|
| ServiceAccount 作成可否 | `serviceAccount.create` | ServiceAccount リソース自体の生成制御 |
| ServiceAccount アノテーション | `serviceAccount.annotations` | ServiceAccount `metadata.annotations`(IRSA 等) |
| ServiceAccount 名 | `serviceAccount.name` | `spec.template.spec.serviceAccountName` |
| API トークン自動マウント | `serviceAccount.automountToken` | `spec.template.spec.automountServiceAccountToken` |
| RBAC リソース作成可否 | `rbac.create` | Role / RoleBinding リソース自体の生成制御 |

### セキュリティコンテキスト

| 用途 | キー | テンプレート上の参照箇所 |
|---|---|---|
| Pod レベルセキュリティ | `podSecurityContext` | `spec.template.spec.securityContext` |
| コンテナレベルセキュリティ | `containerSecurityContext` | `spec.template.spec.containers[].securityContext` |

### リソース要求・制限

| 用途 | キー | テンプレート上の参照箇所 |
|---|---|---|
| リソース要求量 | `resources.requests` | `spec.template.spec.containers[].resources.requests` |
| リソース上限 | `resources.limits` | `spec.template.spec.containers[].resources.limits` |

### スケジューリング

| 用途 | キー | テンプレート上の参照箇所 |
|---|---|---|
| ノードセレクタ | `nodeSelector` | `spec.template.spec.nodeSelector` |
| トレレーション | `tolerations` | `spec.template.spec.tolerations` |
| アフィニティ | `affinity` | `spec.template.spec.affinity` |
| トポロジー分散 | `topologySpreadConstraints` | `spec.template.spec.topologySpreadConstraints` |
| 優先度クラス | `priorityClassName` | `spec.template.spec.priorityClassName` |

### DNS

| 用途 | キー | テンプレート上の参照箇所 |
|---|---|---|
| DNS ポリシー | `dnsPolicy` | `spec.template.spec.dnsPolicy` |
| カスタム DNS 設定 | `dnsConfig` | `spec.template.spec.dnsConfig` |

### 初期化・終了

| 用途 | キー | テンプレート上の参照箇所 |
|---|---|---|
| 初期化コンテナ | `initContainers` | `spec.template.spec.initContainers` |
| グレースフル終了待機秒数 | `terminationGracePeriodSeconds` | `spec.template.spec.terminationGracePeriodSeconds` |

### 拡張ポイント(全ワークロード共通)

| 用途 | キー | テンプレート上の参照箇所 |
|---|---|---|
| 追加環境変数 | `extraEnv` | `spec.template.spec.containers[].env` |
| 追加環境変数ソース | `extraEnvFrom` | `spec.template.spec.containers[].envFrom` |
| 追加ボリューム | `extraVolumes` | `spec.template.spec.volumes` |
| 追加ボリュームマウント | `extraVolumeMounts` | `spec.template.spec.containers[].volumeMounts` |

### 付随リソース(任意作成)

| 用途 | キー | テンプレート上の参照箇所 |
|---|---|---|
| NetworkPolicy 作成可否 | `networkPolicy.enabled` | NetworkPolicy リソース自体の生成制御 |
| ConfigMap 自動生成可否 | `config.enabled` | ConfigMap リソース自体の生成制御 |

### Service(Deployment / StatefulSet / DaemonSet)

| 用途 | キー | テンプレート上の参照箇所 |
|---|---|---|
| Service タイプ | `service.type` | Service `spec.type` |
| Service 公開ポート | `service.port` | Service `spec.ports[].port` |
| コンテナリッスンポート | `service.containerPort` | `spec.template.spec.containers[].ports[].containerPort` |
| ポート名 | `service.portName` | Service `spec.ports[].name` および `containers[].ports[].name` |
| プロトコル | `service.protocol` | Service `spec.ports[].protocol` |
| Headless Service フラグ（**StatefulSet のみ**） | `service.headless` | Service `spec.clusterIP: None` |

### Ingress(Deployment / StatefulSet)

| 用途 | キー | テンプレート上の参照箇所 |
|---|---|---|
| Ingress 作成可否 | `ingress.enabled` | Ingress リソース自体の生成制御 |
| IngressClass 名 | `ingress.className` | Ingress `spec.ingressClassName` |
| Ingress アノテーション | `ingress.annotations` | Ingress `metadata.annotations` |
| ルーティングルール | `ingress.hosts` | Ingress `spec.rules` |
| TLS 設定 | `ingress.tls` | Ingress `spec.tls` |

### プローブ(Deployment / StatefulSet / DaemonSet)

| 用途 | キー | テンプレート上の参照箇所 |
|---|---|---|
| ライブネスプローブ | `livenessProbe` | `spec.template.spec.containers[].livenessProbe` |
| レディネスプローブ | `readinessProbe` | `spec.template.spec.containers[].readinessProbe` |
| スタートアッププローブ作成可否 | `startupProbe.enabled` | startupProbe ブロック自体の出力制御 |
| スタートアッププローブ本体 | `startupProbe.httpGet` ほか | `spec.template.spec.containers[].startupProbe` |

### レプリカ・更新戦略

このセクションのキーはワークロード種別ごとに適用対象が異なる。各キーの括弧内を確認し、該当しないワークロードでは定義しない。

| 用途 | キー | テンプレート上の参照箇所 |
|---|---|---|
| レプリカ数（**Deployment / StatefulSet のみ**） | `replicaCount` | `spec.replicas` |
| 更新戦略（**Deployment のみ**） | `strategy` | Deployment `spec.strategy` |
| 更新戦略（**DaemonSet / StatefulSet のみ**） | `updateStrategy` | DaemonSet `spec.updateStrategy` / StatefulSet `spec.updateStrategy` |
| Pod 管理ポリシー（**StatefulSet のみ**） | `podManagementPolicy` | StatefulSet `spec.podManagementPolicy` |
| リビジョン履歴保持数（**Deployment / StatefulSet / DaemonSet**） | `revisionHistoryLimit` | `spec.revisionHistoryLimit` |

### オートスケーリング / 中断予算(Deployment / StatefulSet)

| 用途 | キー | テンプレート上の参照箇所 |
|---|---|---|
| HPA 作成可否 | `autoscaling.enabled` | HorizontalPodAutoscaler リソース自体の生成制御 |
| 最小レプリカ数 | `autoscaling.minReplicas` | HPA `spec.minReplicas` |
| 最大レプリカ数 | `autoscaling.maxReplicas` | HPA `spec.maxReplicas` |
| CPU 使用率閾値 | `autoscaling.targetCPUUtilizationPercentage` | HPA `spec.metrics`(CPU Resource metric) |
| PDB 作成可否 | `podDisruptionBudget.enabled` | PodDisruptionBudget リソース自体の生成制御 |
| 最小可用 Pod 数 | `podDisruptionBudget.minAvailable` | PDB `spec.minAvailable` |

### 永続化(Deployment / StatefulSet)

| 用途 | キー | テンプレート上の参照箇所 |
|---|---|---|
| 永続化有効化 | `persistence.enabled` | PVC または StatefulSet `volumeClaimTemplates` の生成制御 |
| StorageClass 名 | `persistence.storageClass` | PVC `spec.storageClassName` / `volumeClaimTemplates[].spec.storageClassName` |
| アクセスモード | `persistence.accessModes` | PVC `spec.accessModes` / `volumeClaimTemplates[].spec.accessModes` |
| ストレージサイズ | `persistence.size` | PVC `spec.resources.requests.storage` |
| PVC 保持ポリシー（**StatefulSet のみ**） | `persistentVolumeClaimRetentionPolicy.whenDeleted` | StatefulSet `spec.persistentVolumeClaimRetentionPolicy.whenDeleted` |
| 〃 | `persistentVolumeClaimRetentionPolicy.whenScaled` | StatefulSet `spec.persistentVolumeClaimRetentionPolicy.whenScaled` |

### Job / CronJob（**Job / CronJob のみ**）

| 用途 | キー | テンプレート上の参照箇所 |
|---|---|---|
| 実行スケジュール(CronJob) | `schedule` | CronJob `spec.schedule` |
| タイムゾーン(CronJob) | `timeZone` | CronJob `spec.timeZone` |
| 同時実行ポリシー(CronJob) | `concurrencyPolicy` | CronJob `spec.concurrencyPolicy` |
| 開始期限(CronJob) | `startingDeadlineSeconds` | CronJob `spec.startingDeadlineSeconds` |
| 成功ジョブ履歴保持数(CronJob) | `successfulJobsHistoryLimit` | CronJob `spec.successfulJobsHistoryLimit` |
| 失敗ジョブ履歴保持数(CronJob) | `failedJobsHistoryLimit` | CronJob `spec.failedJobsHistoryLimit` |
| 一時停止(CronJob) | `suspend` | CronJob `spec.suspend` |
| 再起動ポリシー(Job / CronJob) | `restartPolicy` | `spec.template.spec.restartPolicy` |
| バックオフ上限(Job / CronJob) | `backoffLimit` | Job `spec.backoffLimit`(CronJob は `spec.jobTemplate.spec.backoffLimit`) |
| 実行期限(Job / CronJob) | `activeDeadlineSeconds` | Job `spec.activeDeadlineSeconds`(CronJob は `spec.jobTemplate.spec.activeDeadlineSeconds`) |
| 完了後 TTL(Job / CronJob) | `ttlSecondsAfterFinished` | Job `spec.ttlSecondsAfterFinished` |
| 必要完了数(Job / CronJob) | `completions` | Job `spec.completions` |
| 並列実行数(Job / CronJob) | `parallelism` | Job `spec.parallelism` |

### DaemonSet 特有（**DaemonSet のみ**）

| 用途 | キー | テンプレート上の参照箇所 |
|---|---|---|
| ホストネットワーク使用 | `hostNetwork` | `spec.template.spec.hostNetwork` |
| ホスト PID 名前空間共有 | `hostPID` | `spec.template.spec.hostPID` |


---

**設計原則(迷ったとき用)**:
- values の構造は対応する **Kubernetes API の階層と一致** させる。Pod レベルのフィールドはトップレベル(または Pod 関連グループ)、コンテナレベルのフィールドは `image.*` のようにコンテナ単位グループに置く。
- リソースの **作成可否を切り替えるフラグ** は、そのリソースを表すマップ直下に `enabled` を置く(`networkPolicy.enabled`, `ingress.enabled`, `autoscaling.enabled`, `podDisruptionBudget.enabled`, `persistence.enabled`, `config.enabled`, `startupProbe.enabled`, `rbac.create`, `serviceAccount.create`)。例外として、Job/CronJob の `suspend` のように Kubernetes API 自体が単一フィールドで持っているものは API 名に従う。
- 「追加で挿し込むだけ」の拡張ポイントは `extra*` 接頭辞で統一する(`extraEnv`, `extraEnvFrom`, `extraVolumes`, `extraVolumeMounts`, `extraLabels`)。

---

## 型を明示する

YAML の型強制は直感に反することがあるため、**文字列は必ずクォートで囲む**。整数についても、桁あふれ・指数表記化のリスクがある場合は文字列として保持し、テンプレート側で `{{ int $value }}` により整数へ変換する。`!!string` などの YAML 型タグは 1 度のパースで失われるため依存しない。

**良い例**:
```yaml
image:
  repository: "myorg/myapp"
  digest: "sha256:1234e10abcdef..."
appVersion: "2.7.1"
maxSurge: "25%"
largeNumber: "12345678901234"
```
```gotemplate
replicas: {{ int .Values.largeNumber }}
```

**悪い例**:
```yaml
image:
  digest: sha256:1234e10abcdef...
appVersion: 2.7.1
enabled: "false"
largeNumber: 12345678901234
```

理由:
- `2.7.1` はクォートがないと環境によって float として解釈される。`1234e10` のような git SHA は指数表記として誤解釈される。
- `enabled: "false"` は文字列の `"false"` であり、ブール値の `false` とは別物。テンプレートの `if` 判定で必ず真になり事故を起こす。
- `12345678901234` のような大きな整数はパーサーによって科学的記数法に丸められる可能性がある。

---

## `--set` での上書きやすさを優先する

values は `values.yaml`、`-f` 指定の values ファイル、`--set` / `--set-string` の 3 経路から上書きされる。表現力が最も低い `--set` でも扱えるよう、**リスト構造ではなく、キー名を持つマップ構造とする**。

**良い例**:
```yaml
servers:
  foo:
    port: 80
  bar:
    port: 81
```
```bash
helm install myapp ./myapp --set servers.foo.port=8080
```

**悪い例**:
```yaml
servers:
  - name: foo
    port: 80
  - name: bar
    port: 81
```
```bash
helm install myapp ./myapp --set servers[0].port=8080
```

理由:
- リスト構造はインデックス参照(`servers[0]`)が必要で、要素の順序が変わると参照先も変わる。`--set` 指定者がリストの順序を把握している前提となり壊れやすい。
- マップ構造なら `servers.foo.port` と意味のあるキーで指定でき、順序変更にも強い。

---

## values.yaml のコメントルール

`values.yaml` で定義された **すべてのプロパティに `# --` コメントを付ける**。コメントの最初の文は **プロパティ名で始め**、用途を少なくとも 1 文で説明する。

**良い例**:
```yaml
# -- serverHost は Web サーバのホスト名
serverHost: "example.com"
# -- serverPort は Web サーバの HTTP リッスンポート
serverPort: 9191
```

**悪い例**(プロパティ名で始まっていない):
```yaml
# -- Web サーバのホスト名
serverHost: "example.com"
```

**悪い例**(コメントがない):
```yaml
serverHost: "example.com"
serverPort: 9191
```

理由:
- プロパティ名で始めることで `grep` による検索が容易になる。
- `# --` は helm-docs がドキュメントコメントとして認識する書式であり、helm-docs 導入時に README の設定値テーブルを自動生成できる。

### 内部補足コメント

利用者向けの説明ではなく、チャート開発者向けの補足情報を残したい場合は、通常の `#` コメントを併記してよい。`# --` と `#` を使い分けることで、利用者向け説明と内部メモを区別できる。

```yaml
# このキーは v2.0 で廃止予定。移行先は newServerHost。
# -- serverHost は Web サーバのホスト名
serverHost: "example.com"
```

### セクション区切りコメント

values.yaml 内のキーが多い場合は、通常の `#` コメントでセクションを区切ることを推奨する。

```yaml
##
# イメージ・レジストリ
##

# -- image.repository はコンテナイメージのリポジトリ
image:
  repository: "myorg/myapp"
  # -- image.digest はコンテナイメージの digest
  digest: ""
  # -- image.pullPolicy はイメージプルポリシー
  pullPolicy: IfNotPresent

##
# Service
##

# -- service.type は Service のタイプ
service:
  type: ClusterIP
  # -- service.port は Service の公開ポート
  port: 80
```

---

## 環境別 values ファイルの記述ルール

環境別 values ファイル(`values-dev.yaml` / `values-stg.yaml` / `values-prod.yaml`)は **差分だけを記述する**。`values.yaml` の内容を丸ごとコピーしてはならない。

理由:
- 差分だけにすることで、各環境でどの値を変えているかが一目で分かる。
- `values.yaml` のデフォルト値を変更したとき、環境別ファイルが自動的に追従する。全コピーしていると環境ごとに手動更新が必要になり、更新漏れが発生する。

### 必須オーバーライドキー

以下のキーは `values-dev.yaml` / `values-stg.yaml` / `values-prod.yaml` で必ず値を上書きする。

| キー | 理由 |
|---|---|
| `replicaCount` | 環境ごとに台数を変更可能とする |
| `image.repository` | 環境別にリポジトリが異なるため |
| `resources.requests` | 環境のトラフィック量に応じて変える |
| `resources.limits` | 同上 |

その他のキーについては必要に応じてオーバーライドする。

