# ラベルとアノテーション

本リファレンスではラベルとアノテーションを使用する際のルールについて記述します。

---

## ラベルとアノテーションの使い分け

メタデータは以下の基準で **ラベル** か **アノテーション** かを使い分ける。

- **ラベル**: Kubernetes がリソースを識別するために使用する、または運用者がシステムを問い合わせる目的で使用するメタデータ
- **アノテーション**: クエリ用途ではない、ツール・ライブラリ・運用者向けの追加情報
- **Helm hook**: 常にアノテーションとする(`helm.sh/hook` 名前空間)

ラベル値には以下の制約があるため、Kubernetes API の規則(63 文字以下、`[a-zA-Z0-9._-]` のみ、先頭末尾は英数字)を満たすことを `values.schema.json` で強制する。アノテーションには文字種制約はないが、サイズ上限(256 KB)に注意する。

---

## 標準ラベル

すべてのチャートが生成するすべてのリソースの `metadata.labels` には、**以下 7 ラベルをすべて付与する**。任意項目は存在しない。値の出所も以下の通りに固定する。

| ラベル | 値 | 出所 |
|---|---|---|
| `app.kubernetes.io/name` | `{{ include "chart.name" . }}` | `Chart.Name`(または `nameOverride`) |
| `app.kubernetes.io/instance` | `{{ .Release.Name }}` | リリース名 |
| `app.kubernetes.io/version` | `{{ .Chart.AppVersion \| quote }}` | `Chart.AppVersion` |
| `app.kubernetes.io/managed-by` | `{{ .Release.Service }}` | リリースサービス(通常 `Helm`) |
| `app.kubernetes.io/component` | `{{ .Values.component }}` | values の `component` 必須項目 |
| `app.kubernetes.io/part-of` | `{{ .Values.partOf \| default .Chart.Name }}` | values の `partOf`(未指定時は `Chart.Name`) |
| `helm.sh/chart` | `{{ printf "%s-%s" .Chart.Name .Chart.Version \| replace "+" "_" \| trunc 63 \| trimSuffix "-" }}` | チャート名とバージョン |

### `helm.sh/chart` ヘルパーの実装

`helm.sh/chart` ラベルの値は `name-version` 形式とする。Kubernetes のラベル値には `+` が使えないため、SemVer の build metadata を含む可能性のある `.Chart.Version` に対して **必ず `+` を `_` に置換**し、63 文字制限に合わせて `trunc 63` を通す。

```gotemplate
{{/* templates/_helpers.tpl */}}
{{- define "myapp.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}
```

理由:
- `.Chart.Version` が `1.4.2+build.5` の場合、`+` を含むラベル値となり apply がバリデーションエラーで失敗する。
- 63 文字制限を超えたときに切り詰められず apply 失敗の原因になる。

### `app.kubernetes.io/version` のクォート

`app.kubernetes.io/version` は `{{ .Chart.AppVersion | quote }}` で出力する。クォートがないと `appVersion` が数値として解釈されるリスクがある。

### `component` の値ルール

- **values.yaml の `component` は必須項目とし、`values.schema.json` で `required` 指定する**
- 値は **Pod が果たす役割が一目でわかる英小文字の名前** とする(例: `web`, `worker`, `scheduler`, `agent`, `proxy` など)
- 1 チャートに複数の役割の Pod が含まれる場合、それぞれのリソースで適切な値を設定する

### `partOf` の値ルール

- values.yaml の `partOf` は **任意項目** とする
- 未指定時の既定値は `Chart.Name` とする(スタンドアロンチャートの扱い)
- 複数チャートを束ねて 1 つの製品を構成する場合は、その製品名を指定する

**良い例**:
```yaml
# values.yaml
component: web
partOf: ecommerce-platform
```
```gotemplate
{{/* templates/_helpers.tpl */}}
{{- define "myapp.labels" -}}
helm.sh/chart: {{ include "myapp.chart" . }}
{{ include "myapp.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.extraLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}
```

**悪い例**:
```yaml
# values.yaml
# component が未指定 → schema 違反でエラー
```
```gotemplate
{{- define "myapp.labels" -}}
app.kubernetes.io/name: {{ include "myapp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{/* version, managed-by, chart, component, part-of がすべて欠落 */}}
{{- end }}
```

理由:
- 7 ラベルすべてを必須にすることで、`kubectl get pods -l app.kubernetes.io/version=2.7.1` のような横断クエリ、Prometheus/Grafana のラベル軸、Lens/k9s などのツール表示が常に機能する。
- 値の出所を機械的に固定することで、チャート作成者ごとのブレを排除する。
- `component` を `values.schema.json` で必須化することで、未設定のチャートが CI 段階で止まる。

---

## selectorLabels と labels の分離

Deployment / StatefulSet / DaemonSet / ReplicaSet / Job の `spec.selector.matchLabels` は **作成後に変更不可** という Kubernetes API 上の制約がある。`helm upgrade` で `matchLabels` の中身が 1 文字でも変わると `field is immutable` エラーで失敗し、`helm uninstall` してから入れ直す以外に復旧手段がない(StatefulSet では実質サービス停止)。

このため、**ラベルを「リリース間で不変なもの」と「可変なもの」に分けて、それぞれ別のヘルパーで生成する**。

### 不変ラベル(selectorLabels に含める)

| ラベル | 不変である理由 |
|---|---|
| `app.kubernetes.io/name` | チャート名。リネームすれば別チャート扱い |
| `app.kubernetes.io/instance` | リリース名。`helm upgrade` で変わらない |
| `app.kubernetes.io/component` | チャート設計時に決まる固定値 |
| `app.kubernetes.io/part-of` | 同上 |

### 可変ラベル(labels にのみ含め、selectorLabels に含めない)

| ラベル | 可変である理由 |
|---|---|
| `app.kubernetes.io/version` | `appVersion` の更新で変わる |
| `helm.sh/chart` | チャートバージョンの更新で変わる |
| `app.kubernetes.io/managed-by` | デプロイツールを変えれば変わる |
| `extraLabels` | values で何でも入る |

### ヘルパーの参照ルール

- `spec.selector.matchLabels` および `spec.template.metadata.labels` のセレクタ参照箇所には **`selectorLabels` ヘルパー** を使用する
- それ以外の `metadata.labels`(リソース自身のメタデータ、および `spec.template.metadata.labels` の全ラベル)には **`labels` ヘルパー** を使用する

**良い例**:
```gotemplate
{{/* templates/_helpers.tpl */}}
{{- define "myapp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "myapp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: {{ .Values.component }}
app.kubernetes.io/part-of: {{ .Values.partOf | default .Chart.Name }}
{{- end }}

{{- define "myapp.labels" -}}
helm.sh/chart: {{ include "myapp.chart" . }}
{{ include "myapp.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.extraLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}
```
```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  selector:
    matchLabels:
      {{- include "myapp.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "myapp.labels" . | nindent 8 }}
```

**悪い例**:
```gotemplate
{{/* selectorLabels に可変ラベルを含めている */}}
{{- define "myapp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "myapp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
helm.sh/chart: {{ include "myapp.chart" . }}
{{- end }}
```
```yaml
# spec.selector.matchLabels に labels(全部入り)を渡している
spec:
  selector:
    matchLabels:
      {{- include "myapp.labels" . | nindent 6 }}
```

理由:
- `helm upgrade` で `appVersion` を `2.7.1` → `2.7.2` に上げると、desired な `matchLabels` の `version` 値が変わる。Kubernetes API は `field is immutable` でアップグレードを拒否し、復旧には `helm uninstall` が必要となる。
- selector を `name + instance + component + part-of` に絞ることで、リリース間で値が不変となり、アップグレードが常に成功する。
- selector は部分集合一致なので、ロールアウト中の新旧 Pod 両方を捕捉できる(問題なし)。
- `kubectl get pods -l app.kubernetes.io/version=2.7.1` で新バージョンの Pod だけ抽出するクエリは、`labels` 側に `version` が含まれているので変わらず可能。

---

## extraLabels の合流先と予約名前空間

`extraLabels` は values から任意のラベルを追加するための拡張ポイントとする。以下のルールに従う。

- **`extraLabels` は `labels` ヘルパーにのみマージし、`selectorLabels` には決してマージしない**(マージすると selector 不変原則を破る)
- **`extraLabels` のキーに以下の予約名前空間を使用してはならない**:
  - `app.kubernetes.io/`
  - `helm.sh/`
  - `kubernetes.io/`
- **このルールは `values.schema.json` の `patternProperties` で機械的に強制する**

**良い例**:
```yaml
# values.yaml
extraLabels:
  team: platform
  cost-center: "1234"
  environment: production
```
```json
// values.schema.json(抜粋)
{
  "definitions": {
    "labelsMap": {
      "type": "object",
      "additionalProperties": { "type": "string" },
      "patternProperties": {
        "^(app\\.kubernetes\\.io/|helm\\.sh/|kubernetes\\.io/)": false
      }
    }
  },
  "properties": {
    "extraLabels": { "$ref": "#/definitions/labelsMap" }
  }
}
```

**悪い例**:
```yaml
# values.yaml
extraLabels:
  app.kubernetes.io/name: other         # 規約ラベルの上書き → schema 違反
  helm.sh/chart: fake-1.0.0             # 規約ラベルの上書き → schema 違反
  kubernetes.io/arch: amd64             # Kubernetes 予約 → schema 違反
```

理由:
- 規約ラベル(`app.kubernetes.io/*`, `helm.sh/*`)は kustomize, ArgoCD, Prometheus operator, Lens, k9s などのエコシステムツールが意味を前提に読む。上書きを許すとツールが期待する値が壊れる。
- `app.kubernetes.io/name` を `extraLabels` で上書きすると、`labels` 側だけが上書きされて `selectorLabels` 側は元の値のままとなり、selector が Pod を捕捉できなくなって Deployment が永久に「desired = 3, available = 0」状態になる。
- `kubernetes.io/` 名前空間は Kubernetes 自身が予約しており(`kubernetes.io/arch`, `kubernetes.io/hostname` など)、ユーザーが任意の値を入れる場所ではない。

---

## アノテーションの方針

アノテーションは以下のルールに従う。

### 1. チャート側でアノテーションをハードコードしない

チャートのテンプレートに固定のアノテーションを直接書かない。アノテーションはすべて以下の values 経由の pass-through とする:

- Pod テンプレート: `podAnnotations`
- ServiceAccount: `serviceAccount.annotations`
- Ingress: `ingress.annotations`
- Service: `service.annotations`(必要な場合)

### 2. Helm hook の必須アノテーション

Helm hook を使用する場合、以下の **3 アノテーションを必ず揃えて明示する**。デフォルト任せにしない。

| アノテーション | 用途 | 既定値 |
|---|---|---|
| `helm.sh/hook` | hook の種類(`pre-install`, `post-install`, `pre-upgrade` など) | 必須・既定なし |
| `helm.sh/hook-weight` | 同種 hook の実行順序(数値、小さい順に実行) | `"0"` |
| `helm.sh/hook-delete-policy` | hook リソースの削除タイミング | `before-hook-creation,hook-succeeded` |

### 3. pass-through アノテーションの予約名前空間

`podAnnotations`, `serviceAccount.annotations`, `ingress.annotations`, `service.annotations` のキーに以下の予約名前空間を使用してはならない。

- `kubectl.kubernetes.io/` (例: `kubectl.kubernetes.io/restartedAt` は `kubectl rollout restart` 専用)
- `deployment.kubernetes.io/` (例: `deployment.kubernetes.io/revision` は Deployment コントローラ専用)
- `pod.kubernetes.io/` (Kubernetes 内部用)
- `app.kubernetes.io/` (規約ラベル名前空間。ラベルとして使うべき)
- `helm.sh/` (Helm hook 用)
- `kubernetes.io/` (Kubernetes 予約)

### 4. 明示的に許可するアノテーション(EKS / AWS)

以下のキーおよびプレフィックスは、EKS および AWS Load Balancer Controller / ALB Ingress Controller で必要なため、**例外として許可する**。

| キー / プレフィックス | 用途 | 適用先 |
|---|---|---|
| `eks.amazonaws.com/role-arn` | IRSA で IAM ロールを ServiceAccount に紐付ける | `serviceAccount.annotations` |
| `eks.amazonaws.com/skip-containers` | IRSA を特定コンテナで無効化する(カンマ区切りのコンテナ名) | `serviceAccount.annotations` |
| `eks.amazonaws.com/sts-regional-endpoints` | STS のリージョナルエンドポイント使用を制御(`true`/`false`) | `serviceAccount.annotations` |
| `eks.amazonaws.com/audience` | IRSA の OIDC オーディエンスを上書き | `serviceAccount.annotations` |
| `service.beta.kubernetes.io/aws-load-balancer-` で始まるキー | AWS Load Balancer Controller(NLB/CLB)の挙動制御(タイプ、スキーマ、ヘルスチェック、ターゲットグループ属性 等) | `service.annotations` |
| `alb.ingress.kubernetes.io/` で始まるキー | ALB Ingress Controller の挙動制御(scheme, target-type, listen-ports, certificate-arn, ヘルスチェック 等) | `ingress.annotations` |

### 5. ルールの強制方法

上記 3 と 4 のルールは **`values.schema.json` の `patternProperties` で機械的に強制する**。

**良い例**:
```yaml
# values.yaml
podAnnotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "9090"
serviceAccount:
  create: true
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/myapp-role
ingress:
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
service:
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-type: nlb
    service.beta.kubernetes.io/aws-load-balancer-scheme: internal
```
```yaml
# templates/migration-job.yaml(Helm hook の正しい例)
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "myapp.fullname" . }}-migrate
  annotations:
    "helm.sh/hook": pre-upgrade
    "helm.sh/hook-weight": "0"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
```

**悪い例**:
```yaml
# values.yaml
podAnnotations:
  kubectl.kubernetes.io/restartedAt: "2026-01-01T00:00:00Z"  # schema 違反
  deployment.kubernetes.io/revision: "5"                      # schema 違反
  app.kubernetes.io/name: other                               # schema 違反
```
```gotemplate
{{/* templates/deployment.yaml: チャート側でアノテーションをハードコード */}}
metadata:
  annotations:
    prometheus.io/scrape: "true"        # values 経由にすべき
    deployment.kubernetes.io/revision: "1"  # 予約名前空間
```
```yaml
# templates/migration-job.yaml(Helm hook の不完全指定)
metadata:
  annotations:
    "helm.sh/hook": pre-upgrade
    # hook-weight と hook-delete-policy が欠落
    # → hook リソースが残り続け、次回 install で already exists エラー
```

理由:
- `kubectl.kubernetes.io/restartedAt` は `kubectl rollout restart` がタイムスタンプを書き込んで Pod 再起動を起こす仕組み。values に固定値で書くと毎回同じ値が適用され、再起動が起きなくなる(または毎回起きる)。
- `deployment.kubernetes.io/revision` は Deployment コントローラが管理するリビジョン番号。手動で書くと history が壊れる。
- `helm.sh/hook-delete-policy` を省略すると、hook で作った Job/ConfigMap がクラスタに残り続け、次回 `helm install` で `already exists` エラーになる。
- `helm.sh/hook-weight` を省略すると、複数 hook の実行順序が不定になる。
- チャート側でアノテーションをハードコードすると、ユーザーが無効化できず、別の監視ツール等への移行時にチャート本体の修正が必要になる。

---

## values.schema.json による検証の強制

本ルール(`extraLabels` の予約名前空間禁止、pass-through アノテーションの予約名前空間禁止と許可リスト、`component` の必須化など)は、**すべて `values.schema.json` で機械的に強制する**。`_helpers.tpl` 内に `fail` 関数による検証ロジックを書かない。

理由:
- `_helpers.tpl` がクリーンに保たれる(検証ロジックと描画ロジックが混ざらない)
- `helm lint` および `helm install` の段階で CI が検出できる(クラスタへ送る前に止まる)
- エラーメッセージが JSON Schema 標準で統一される
- VS Code の Helm / YAML LSP 拡張でリアルタイム警告が出る
- `values.schema.json` はチャートの必須ファイルとして本ルール体系で別途強制する