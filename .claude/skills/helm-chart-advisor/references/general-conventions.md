# 一般的な慣例

本リファレンスでは一般的なルールについて記述します。

---

## チャート名

チャート名は小文字の英字と数字で構成してください。単語はハイフン（-）で区切ることができます。
大文字もアンダースコアも使用できません。また、ドットも使用しないでください。

**良い例**:
> aws-cluster-autoscaler

**悪い例**:
> aws_cluster_autoscaler
> aws.cluster.autoscaler
> awsClusterAutoscaler

---

## Helmチャートのバージョン番号

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

### Kubernetesラベルへのバージョン格納

Kubernetes のラベル値には `+` が使えないため、SemVer の build metadata を含む可能性のある `.Chart.Version` をラベルに入れる際は **必ず `+` を `_` に置換**し、63 文字制限に合わせて `trunc 63` を通す。`helm.sh/chart` ラベルは `name-version` 形式で出力する。

**良い例**:
```gotemplate
{{/* templates/_helpers.tpl */}}
{{- define "myapp.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}
```
```yaml
# templates/deployment.yaml
metadata:
  labels:
    helm.sh/chart: {{ include "myapp.chart" . | quote }}
    app.kubernetes.io/name: {{ include "myapp.name" . }}
    app.kubernetes.io/instance: {{ .Release.Name }}
    app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
    app.kubernetes.io/managed-by: {{ .Release.Service }}
```

**悪い例**:
```yaml
# templates/deployment.yaml
metadata:
  labels:
    helm.sh/chart: "{{ .Chart.Name }}-{{ .Chart.Version }}"
    app.kubernetes.io/version: {{ .Chart.AppVersion }}
```

理由:
- `.Chart.Version` が `1.4.2+build.5` の場合、`+` を含むラベル値となり apply がバリデーションエラーで失敗する。
- 63 文字制限を超えたときに切り詰められず apply 失敗の原因になる。
- `app.kubernetes.io/version` がクォートされておらず、`appVersion` が数値として解釈されるリスクがある。

### Dockerイメージタグとの関係

Docker タグは英数字とダッシュしか許容せず `+` が使えない。よって `appVersion` には build metadata を含めず、`image.tag` のフォールバックとして安全に使える形に保つ。

**良い例**:
```yaml
# Chart.yaml
appVersion: "2.7.1"
```
```yaml
# templates/deployment.yaml
image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
```

**悪い例**:
```yaml
# Chart.yaml
appVersion: "2.7.1+build.5"
```
```yaml
# templates/deployment.yaml
image: "{{ .Values.image.repository }}:{{ .Chart.AppVersion }}"
```

理由:
- `2.7.1+build.5` は Docker タグとして無効で `image pull` に失敗する。build metadata が必要なら `Chart.yaml` の `version` 側に付ける。

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

## YAML のフォーマット

YAML ファイルは **スペース 2 つでインデント** する。タブは使用しない。

**良い例**:
```yaml
spec:
  replicas: 3
  selector:
    matchLabels:
      app: myapp
```

**悪い例**:
```yaml
spec:
    replicas: 3
    selector:
        matchLabels:
            app: myapp
```

理由:
- 4スペース、タブ、不揃いなインデントは Helm コミュニティの慣例から外れ、レビュー時の差分やテンプレート出力との混在で読みづらくなる。

---

## "Helm" と "Chart" という単語の使い方

ドキュメント・README・コミットメッセージなどの文章中での表記ルール:

- **Helm**: プロジェクト全体を指す固有名詞。先頭は大文字。
- **`helm`**: クライアント側のコマンドを指すときは小文字でコード表記。
- **chart**: 固有名詞ではないため大文字にしない。
- **`Chart.yaml`**: ファイル名はケースセンシティブなので、必ずこの表記を守る。
- 迷ったら **Helm**(大文字 H)を使う。

**良い例**:
```markdown
Helm はパッケージマネージャです。`helm install` でチャートをインストールできます。
チャートのメタデータは `Chart.yaml` に記述します。
```

**悪い例**:
```markdown
helm はパッケージマネージャです。`Helm install` でChartをインストールできます。
チャートのメタデータは `chart.yaml` に記述します。
```

理由:
- `helm`(プロジェクト名としての小文字)、`Helm install`(コマンドなのに大文字)、`Chart`(固有名詞でないのに大文字)、`chart.yaml`(ファイル名のケース違反)は、いずれも公式ドキュメントの規約に反する。

---

## チャートテンプレートと namespace

チャートテンプレートの `metadata` セクションに **`namespace` を直接定義しない**。Helm はテンプレートをそのままレンダリングして Kubernetes クライアントに送るだけなので、適用先 namespace は `helm install --namespace` などのフラグで指定する。

**良い例**:
```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
```
```bash
helm install myapp ./myapp --namespace production
```

**悪い例**:
```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
  namespace: production
```

理由:
- テンプレートに namespace をハードコードすると、同じチャートを複数 namespace に再利用できない。
- `helm install --namespace` や GitOps ツール(flux, spinnaker など)から渡される namespace と食い違い、デプロイ先が混乱する。
- namespace の決定権はチャート側ではなく **デプロイを実行するクライアント側** に置くのが Helm の設計思想。
