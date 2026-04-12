# RBAC 基本ルール

本リファレンスでは RBAC リソースの基本構造に関するルールを定める。

`rbac.create` のデフォルトは **`false`** とする。RBAC リソース（Role / RoleBinding）は Kubernetes API への権限付与であり、K8s API にアクセスしないアプリには不要である。なお、`rbac.create` と `automountToken` は独立した判断である。Workload Identity（IRSA 等）を使用するアプリは `automountToken: true` かつ `rbac.create: false` が正当な構成となる。

## ServiceAccount トークンの自動マウント

`serviceAccount.automountToken` の正しい値は、チャートの用途に基づいて以下のように判定する。

| チャートの用途 | 正しい値 | 理由 |
|---|---|---|
| EKS Pod Identity / IRSA / Workload Identity を使用する | `true` | クラウドリソースへの認証に SA トークンが必要 |
| Kubernetes API にアクセスする（オペレータ、コントローラ等） | `true` | K8s API への認証に SA トークンが必要 |
| SA トークンで外部システムに認証する（Vault Agent 等） | `true` | 外部認証に SA トークンが必要 |
| 上記いずれにも該当しない | `false` | SA トークンは不要であり、マウントすると攻撃面が増える |

SA トークンはコンテナ内に JWT ファイルとしてマウントされ、Kubernetes API やクラウドリソースへの認証情報として機能する。Pod が侵害された場合、攻撃者はこのトークンで API サーバやクラウドリソースを操作できるため、不要な場合はマウントしない。

---

## 対象となる RBAC リソース

本ルールが対象とするリソースは以下の通り。

| リソース | スコープ |
|---|---|
| `ServiceAccount` | namespace スコープ |
| `Role` | namespace スコープ |
| `ClusterRole` | クラスタスコープ |
| `RoleBinding` | namespace スコープ |
| `ClusterRoleBinding` | クラスタスコープ |

---

## values 構造

RBAC と ServiceAccount は **別々のトップレベルキーの下に配置する**。

**良い例**:
```yaml
# values.yaml
rbac:
  create: false

serviceAccount:
  create: true
  name: ""
  annotations: {}       # IRSA 等アノテーションベース認証を使用する場合のみ
  automountToken: false
```

`serviceAccount.annotations` およびテンプレートでの pass-through は、IRSA 等アノテーションベースの認証方式を使用する場合に定義する。EKS Pod Identity など SA アノテーションが不要な方式では定義不要である。

**悪い例**:
```yaml
# values.yaml
rbac:
  create: false
  serviceAccount:        # rbac の下に serviceAccount をネストしない
    create: true
```

理由:
- `rbac` と `serviceAccount` は異なる概念である。RBAC は「何ができるか(権限)」、ServiceAccount は「Pod がどの ID で動くか」であり、別々のトップレベルキーに分けることで両者の責務を明確にする。
- ネストすると values のオーバーライドが煩雑になり、どちらか一方だけを変更したい場合の記述が冗長になる。

---

## `rbac.create` のデフォルト

`rbac.create` のデフォルトは **`false`** とする。Role / RoleBinding / ClusterRole / ClusterRoleBinding はデフォルトで作成しない。

Kubernetes API へアクセスする必要があるチャート（オペレータ、コントローラ、一部のバッチ処理等）のみ、values で `rbac.create: true` に上書きする。

**良い例**(通常の業務アプリ、SA トークン不要):
```yaml
# values.yaml
rbac:
  create: false
serviceAccount:
  create: true
  automountToken: false
```

**良い例**(Workload Identity で AWS リソースにアクセス、K8s API アクセスは不要):
```yaml
rbac:
  create: false              # K8s API の RBAC は不要
serviceAccount:
  create: true
  automountToken: true       # Workload Identity に SA トークンが必要
  annotations:
    eks.amazonaws.com/role-arn: "arn:aws:iam::123456789012:role/my-role"
```

**良い例**(K8s API アクセスが必要なオペレータ等):
```yaml
rbac:
  create: true
serviceAccount:
  create: true
  automountToken: true
```

**悪い例**:
```yaml
rbac:
  create: true            # K8s API を使わないのに RBAC を作成
serviceAccount:
  create: true
  automountToken: false
```

理由:
- ほとんどの業務アプリは Kubernetes API にアクセスしない。RBAC リソースを作成してもまったく使われず、クラスタ内にゴミが増えるだけである。
- `rbac.create` は K8s API への権限付与を制御するものであり、`automountToken` とは独立した判断である。Workload Identity を使用するアプリは `automountToken: true` かつ `rbac.create: false` が正当な構成となる。
- secure-by-default 方針により、明示的に必要と判断された場合にのみ K8s API 権限を付与する。

---

## Role と ClusterRole の使い分け

使用する RBAC リソースの種別は、チャートがアクセスするリソースのスコープに基づいて以下のように判定する。

| アクセスするリソースの性質 | 使用する RBAC リソース |
|---|---|
| namespace スコープのリソースのみ（ConfigMap, Secret, Pod 等） | `Role` + `RoleBinding` |
| クラスタスコープのリソース（`Node`, `PersistentVolume`, `StorageClass` 等） | `ClusterRole` + `ClusterRoleBinding` |
| 複数 namespace を横断して監視・制御（オペレータ、コントローラ等） | `ClusterRole` + `ClusterRoleBinding` |
| `nonResourceURLs`（`/metrics`, `/healthz` 等） | `ClusterRole` + `ClusterRoleBinding` |
| ClusterRole の定義を再利用しつつスコープは特定 namespace に限定 | `ClusterRole` + `RoleBinding` |

**良い例**(原則: Role + RoleBinding):
```yaml
# templates/role.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ include "myapp.fullname" . }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "list", "watch"]
    resourceNames:
      - {{ include "myapp.fullname" . }}-config
```
```yaml
# templates/rolebinding.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ include "myapp.fullname" . }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
subjects:
  - kind: ServiceAccount
    name: {{ include "myapp.serviceAccountName" . }}
    namespace: {{ .Release.Namespace }}
roleRef:
  kind: Role
  name: {{ include "myapp.fullname" . }}
  apiGroup: rbac.authorization.k8s.io
```

**良い例**(正当理由あり: ClusterRole + ClusterRoleBinding):
```yaml
# templates/clusterrole.yaml(Node を監視するノードエージェント)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: {{ include "myapp.fullname" . }}
rules:
  - apiGroups: [""]
    resources: ["nodes"]        # Node はクラスタスコープリソース
    verbs: ["get", "list", "watch"]
```

**悪い例**(不要な ClusterRole):
```yaml
# 単に ConfigMap を読むだけなのに ClusterRole を使っている
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: {{ include "myapp.fullname" . }}
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get"]
```

理由:
- Role はスコープが namespace 内に限定されるため、チャートが侵害されても影響範囲がその namespace に閉じ込められる。
- ClusterRole は影響範囲がクラスタ全体に及ぶため、侵害時の被害が桁違いに大きい。
- クラスタスコープリソース(Node, PV 等)にアクセスする必要がない限り、ClusterRole を使う理由はない。

---

## 1 チャート 1 ServiceAccount 原則

**原則として 1 チャートにつき 1 つの ServiceAccount を使用する**。

ただし、チャート内に複数のワークロード(例: メインアプリ + マイグレーションジョブ + バックグラウンドワーカー)があり、それぞれ異なる権限が必要な場合は、ワークロードごとに SA を分離してよい。

**良い例**(1 チャート 1 SA):
```yaml
# values.yaml
serviceAccount:
  create: true
  name: ""
rbac:
  create: false
```

複数のワークロードがあり、それぞれ異なる権限が必要な場合は、**チャート自体を分割する**。1 つのチャートに複数の ServiceAccount を詰め込む構成は採用しない。

理由:
- SA の乱立はレビュー・監査を困難にする。1 チャートに 1 SA が原則であれば、権限の全体像を把握しやすい。
- 複数ワークロードを持つ大規模チャートは、そもそも 1 チャート = 1 アプリケーションの原則から外れている。権限要件が異なるワークロードは別チャートとして切り出す。
- 同じライフサイクルで動く必要があるワークロード群(マイグレーションジョブとアプリ本体等)は、同じ SA を共有するか、親チャート + サブチャート構成で各サブチャートに 1 SA を持たせる。

---

## ServiceAccount 名のヘルパー

ServiceAccount 名を生成するヘルパーは、以下のテンプレートを採用する。
```gotemplate
{{/*
使用する ServiceAccount 名を生成する
*/}}
{{- define "myapp.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
    {{ default (include "myapp.fullname" .) .Values.serviceAccount.name }}
{{- else -}}
    {{ default "default" .Values.serviceAccount.name }}
{{- end -}}
{{- end -}}
```

このヘルパーの挙動:

| `serviceAccount.create` | `serviceAccount.name` | 返される名前 |
|---|---|---|
| `true` | `""`(未指定) | `{fullname}`(例: `myapp-prod`) |
| `true` | `"custom-sa"` | `custom-sa` |
| `false` | `""`(未指定) | `default`(namespace のデフォルト SA) |
| `false` | `"existing-sa"` | `existing-sa`(既存 SA を参照) |

**良い例**:
```gotemplate
# templates/deployment.yaml
spec:
  template:
    spec:
      serviceAccountName: {{ include "myapp.serviceAccountName" . }}
```

**悪い例**:
```gotemplate
# values.serviceAccount.name を直接参照している
spec:
  template:
    spec:
      serviceAccountName: {{ .Values.serviceAccount.name | default .Release.Name }}
```

理由:
- ヘルパーを使うことで、`serviceAccount.create` の true/false と `serviceAccount.name` の有無の組み合わせ(4 パターン)をすべて正しく処理できる。
- 直接参照は `create: false` かつ `name: ""` のケースで `""` を返してしまい、Pod 作成時にバリデーションエラーとなる。
- ヘルパー化することでチャート間の挙動が揃い、レビュー時の認知負荷が下がる。

### Pod Identity / IRSA 利用時の `serviceAccount.name` 明示指定

EKS Pod Identity や IRSA を使用する場合、SA 名は AWS 側の設定（Pod Identity Association の `serviceAccount` フィールド、または IAM Role の trust policy の `sub` 条件）と**完全一致**しなければならない。`fullname`（リリース名依存）をそのまま使うと、リリース名の変更で SA 名が変わり Pod Identity が壊れる。

このため、Pod Identity / IRSA を使用するチャートでは **`serviceAccount.name` を values.yaml で明示的に指定するのが正当な構成** である。ヘルパーは `serviceAccount.name` が指定されていればそれをそのまま返すため、ヘルパー自体の変更は不要。

**良い例**（Pod Identity 使用時）:
```yaml
# values.yaml
serviceAccount:
  create: true
  name: "my-app"                    # Pod Identity Association と一致させる
  annotations:
    eks.amazonaws.com/role-arn: "arn:aws:iam::123456789012:role/my-app"
  automountToken: true
```

`serviceAccount.name` が明示指定されており、かつ Pod Identity / IRSA のアノテーションが設定されている場合、`fullname` を使用していないことは違反ではない。