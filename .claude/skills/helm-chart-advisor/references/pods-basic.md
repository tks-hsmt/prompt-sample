# Pod ベースルール(イメージ / プルポリシー / セレクタ)

本リファレンスではPodおよびPodTemplateの基本的なルールについて記述します。

---

## コンテナイメージの指定

コンテナイメージは **必ず digest(`@sha256:...`)形式で完全固定する**。タグ指定(`latest`, `v1.2.3` を含む)は一切禁止する。

理由:
- タグは **可変**(同じタグが異なるイメージを指すよう上書きされうる)であり、サプライチェーン攻撃のリスクがある
- `latest` / `head` / `canary` のような floating タグはもちろん、`v1.2.3` のような固定見える版番号も、レジストリ側で上書きされうるため本質的にタグは保証にならない
- digest は SHA-256 ハッシュなので、同じ digest は未来永劫同じイメージを指すことが数学的に保証される

**良い例**:
```yaml
# values.yaml
image:
  repository: "123456789012.dkr.ecr.ap-northeast-1.amazonaws.com/myapp"
  digest: "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
  pullPolicy: IfNotPresent
```
```gotemplate
# templates/deployment.yaml
containers:
  - name: {{ .Chart.Name }}
    image: "{{ .Values.image.repository }}@{{ .Values.image.digest }}"
    imagePullPolicy: {{ .Values.image.pullPolicy }}
```

**悪い例**:
```yaml
image:
  repository: "myorg/myapp"
  tag: "latest"              # floating タグ
```
```yaml
image:
  repository: "myorg/myapp"
  tag: "v1.2.3"              # 固定見えるがレジストリ側で上書きされうる
```
```gotemplate
containers:
  - name: {{ .Chart.Name }}
    image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
```

理由:
- タグ指定では同じ `helm upgrade` を 2 回実行したとき、レジストリ側のイメージが入れ替わっていれば別の実体が動く。インシデント調査で「何が動いていたか」を確定できない。
- digest は Kubernetes が起動時にレジストリと突き合わせて検証するため、改ざん検知にもなる。
- CI/CD パイプラインでは、`docker build` → `docker push` 後に出力される digest を `image.digest` へ反映する手順を組む。

### appVersion と Docker タグの関係

Docker タグは英数字とダッシュしか許容せず `+` が使えない。よって `appVersion` には build metadata を含めず、`image.tag` のフォールバックとして安全に使える形に保つ。build metadata が必要なら `Chart.yaml` の `version` 側に付ける。

---

## ImagePullPolicy

`imagePullPolicy` は **必ず `IfNotPresent` とする**。`Always` および `Never` は使用しない。

**良い例**:
```yaml
# values.yaml
image:
  pullPolicy: IfNotPresent
```

**悪い例**:
```yaml
image:
  pullPolicy: Always
```

理由:
- digest で完全固定している前提では、同じ digest は同じイメージを指すことが保証されるので、ノードのキャッシュを信頼してよい。`Always` はネットワーク経由の pull を毎回発生させ、ノード障害時の Pod 再スケジュールを遅らせるだけで得るものがない。
- `Never` はレジストリから pull しないため、新しいノードで起動できない。
- `values.schema.json` で `image.pullPolicy` を `{"const": "IfNotPresent"}` として機械的に強制する。

---

## ImagePullSecrets

プライベートレジストリ認証が必要な場合、`imagePullSecrets` は **ServiceAccount に紐付ける方式を優先する**。Pod レベルの指定は既存 ServiceAccount を変更できない等の例外的ケースに限る。

ECR のみを使用する場合は、**ノードの IAM ロールまたは IRSA(IAM Roles for Service Accounts)で ECR の `GetAuthorizationToken` / `BatchGetImage` / `GetDownloadUrlForLayer` 権限を付与**し、`imagePullSecrets` は空のままとする。

**良い例**(ECR のみ使用):
```yaml
# values.yaml
imagePullSecrets: []          # ECR 使用時は空
serviceAccount:
  create: true
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/myapp
```

**良い例**(Docker Hub プライベートイメージ等、外部レジストリ使用):
```yaml
# values.yaml
serviceAccount:
  create: true
  imagePullSecrets:
    - name: dockerhub-credentials
imagePullSecrets: []
```
```gotemplate
# templates/serviceaccount.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "myapp.serviceAccountName" . }}
{{- with .Values.serviceAccount.imagePullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
```

**悪い例**(Pod レベルに直接書いている):
```yaml
# values.yaml
imagePullSecrets:
  - name: dockerhub-credentials
```
```gotemplate
# templates/deployment.yaml
spec:
  template:
    spec:
      imagePullSecrets:
        {{- toYaml .Values.imagePullSecrets | nindent 8 }}
```

理由:
- ServiceAccount に紐付けておけば、その SA を参照するすべての Pod に自動的に適用される。Pod テンプレートに毎回書く必要がなく、書き漏らしのリスクがない。
- Secret 名を変更したい場合、ServiceAccount 1 箇所の修正で済む。Pod レベル指定では全ワークロードの values を更新する必要がある。
- プラットフォームチームが SA に Secret を紐付け、アプリチームは SA の存在だけを意識すればよいという関心の分離が実現できる。
- EKS の ECR では `imagePullSecrets` 自体が不要になるため、Docker Hub や GHCR 等を使わない限り空のままでよい。

---

## セレクタの明示

Deployment / StatefulSet / DaemonSet / ReplicaSet / Job は **`spec.selector.matchLabels` を必ず明示する**。省略すると `.spec.template.metadata.labels` の全ラベルがセレクタとして使われ、`version` や `chart` などの可変ラベルが混入して `helm upgrade` で `field is immutable` エラーが発生する。

セレクタには **不変ラベルのみで構成される `selectorLabels` ヘルパーを使用する**。

**良い例**:
```gotemplate
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

**悪い例**(セレクタを省略):
```gotemplate
spec:
  # selector がない → template.metadata.labels 全体が暗黙セレクタとなる
  template:
    metadata:
      labels:
        {{- include "myapp.labels" . | nindent 8 }}
```

理由:
- セレクタ省略は Kubernetes の古い動作に依存しており、現在の推奨ではない。
- 暗黙セレクタは可変ラベル(`version`, `chart`)を含むため、`helm upgrade` の 1 回目は通るが、2 回目以降で selector 不一致による immutable エラーが発生する。
