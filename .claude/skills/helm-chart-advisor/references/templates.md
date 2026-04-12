# templates/ ディレクトリ構成

`templates/` 配下のファイルは以下のルールで構成する。

- YAML を出力するテンプレートファイルは拡張子 **`.yaml`** とする。
- レンダリング結果を持たない部分テンプレート(`define` のみを含むファイル)は拡張子 **`.tpl`** とし、ファイル名は **`_helpers.tpl`** とする(先頭アンダースコアにより Helm がリソースとして処理しない)。
- 1 つのリソース定義につき 1 ファイルとする。複数リソースを 1 ファイルに詰め込まない。
- ファイル名は **`{kind}.yaml`** 形式とする(`helm create` 準拠)。`{appname}-{kind}.yaml` のような接頭辞は付けない。
- リソース種別名は原則として **kind 名を英小文字でそのまま** 使う。例外として、3 文字略称が一般的に定着している以下の kind は略称を使う:
  - `HorizontalPodAutoscaler` → `hpa`
  - `PodDisruptionBudget` → `pdb`
  - `PersistentVolumeClaim` → `pvc`
- 同じ kind を複数配置する場合は **`{kind}-{用途}.yaml`** 形式とする。`{用途}` は役割を端的に表す英小文字とする(例: `service-headless.yaml`, `configmap-app.yaml`, `networkpolicy-egress.yaml`)。

**良い例**:
```
templates/
├── _helpers.tpl
├── deployment.yaml
├── service.yaml
├── service-headless.yaml
├── serviceaccount.yaml
├── role.yaml
├── rolebinding.yaml
├── configmap.yaml
├── networkpolicy.yaml
├── hpa.yaml
├── pdb.yaml
├── pvc.yaml
└── ingress.yaml
```

**悪い例**:
```
templates/
├── helpers.tpl                          # 先頭アンダースコアなし
├── myapp-deployment.yaml                # 接頭辞付き
├── myapp-svc.yaml                       # 接頭辞付き + 略称(svc は標準略称ではない)
├── all-resources.yaml                   # 複数リソースが 1 ファイル
├── horizontalpodautoscaler.yaml         # 標準略称があるのにフル名
├── ConfigMap.yaml                       # キャメルケース
└── headless-service.yaml                # {用途}-{kind} の順序が逆
```

理由:
- `helpers.tpl`(先頭アンダースコアなし)は Helm がリソースとして処理しようとしてエラーになる。
- 接頭辞付きの命名はアプリ名変更やリネームに弱く、`helm create` 出力とも乖離する。
- 1 ファイルに複数リソースを詰めると、`helm template` の出力で発生源を特定しづらくなり、CI のリソース別 lint ができなくなる。
- 略称ルールを統一しないと、同じ kind が複数チャート間で `hpa.yaml` / `horizontalpodautoscaler.yaml` / `autoscaler.yaml` のように揺れる。
- `{用途}-{kind}` の順序が逆になると `ls` でソートしたときに同じ kind が隣接しなくなる。

---

## defined テンプレート名

`{{ define }}` で定義したテンプレートは **チャート全体およびすべてのサブチャートからグローバルにアクセス可能** になる。サブチャート間で名前衝突を起こさないよう、**defined テンプレート名はすべてチャート名でネームスペース化する**。

具体的には、**`{チャート名}.{用途}` の形式とし、`{チャート名}` 接頭辞を必ず付与する**。新規チャートは `helm create` で生成し、自動生成されるヘルパーをベースにする。

**良い例**:
```gotemplate
{{- define "nginx.fullname" -}}
{{/* ... */}}
{{- end -}}

{{- define "nginx.labels" -}}
{{/* ... */}}
{{- end -}}

{{- define "nginx.serviceAccountName" -}}
{{/* ... */}}
{{- end -}}
```

**悪い例**:
```gotemplate
{{- define "fullname" -}}
{{/* ... */}}
{{- end -}}

{{- define "labels" -}}
{{/* ... */}}
{{- end -}}
```

理由:
- ネームスペース化されていない `fullname` をサブチャートでも定義していると、どちらが有効になるかが読み込み順に依存し、上書きで意図しないリソース名が生成される。
- チャート名接頭辞を付けておけば、`{{ include "nginx.fullname" . }}` の呼び出し時にどのチャートのヘルパーを参照しているか一目で分かる。

---

## テンプレートのフォーマット

テンプレートは以下のフォーマットで記述する。

- インデントは **スペース 2 つ** とする。タブは使用しない。
- テンプレートディレクティブは **開きブレースの直後と閉じブレースの直前にスペースを 1 つ入れる**(`{{ .foo }}`)。
- 可能な限り **ホワイトスペースを chomp する**(`{{-` / `-}}`)。
- 制御構造(`if` / `with` / `range`)は流れを示すために **テンプレートコード上のインデントを付けてよい**(YAML 出力のインデントとは別)。

**良い例**:
```gotemplate
{{ .foo }}
{{ print "foo" }}
{{- print "bar" -}}

foo:
  {{- range .Values.items }}
  {{ . }}
  {{ end -}}

{{ if $foo -}}
  {{- with .Bar }}Hello{{ end -}}
{{- end -}}
```

**悪い例**:
```gotemplate
{{.foo}}
{{print "foo"}}
{{-print "bar"-}}

foo:
	{{- range .Values.items }}
	{{ . }}
	{{ end -}}
```

理由:
- ブレース内のスペースを省略すると、Go template のパースは通っても可読性が著しく落ちる。
- タブインデントは YAML パーサの種類によっては事故の原因になる。
- chomp を怠ると出力 YAML に不要な空行・空白が混入する(次節参照)。

---

## 生成テンプレートのホワイトスペース

`helm template` でレンダリングした YAML 出力には、**連続する空行を含めない**。論理的な区切りとして 1 行までの空行は許容するが、2 行以上の連続した空行は禁止する。

**良い例**:
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: example
  labels:
    first: first
    second: second
```

**許容できる例**(論理ブロック間の 1 行空行):
```yaml
apiVersion: batch/v1
kind: Job

metadata:
  name: example

  labels:
    first: first
    second: second
```

**悪い例**:
```yaml
apiVersion: batch/v1
kind: Job




metadata:
  name: example




  labels:
    first: first

    second: second
```

理由:
- レンダリング結果に大量の空行があると、`helm template | kubectl diff` などのレビューが極端に読みづらくなる。
- 連続空行は通常、`{{-` / `-}}` の chomp 漏れが原因であり、テンプレートの品質指標として「空行が出ていないか」をチェックする慣習を作るべき。

---

## コメント(YAML コメント vs テンプレートコメント)

テンプレート内のコメントは以下の使い分けを **必ず守る**。

- **原則として、テンプレートコメント `{{- /* ... */ -}}` を使用する**。レンダリング結果に残らないため、生成 YAML を汚さない。
- **`helm install --debug` 実行時に利用者へ警告を見せたい場合に限り、YAML コメント `#` を使用する**。
- **`required` 関数を含むブロックの前後に YAML コメントを書かない**。YAML コメントは `helm template` の段階では除去されず、`required` がコメント内の値を評価してレンダリングエラーになる場合がある。

**良い例**(テンプレートコメント = 通常の解説):
```gotemplate
{{- /*
mychart.shortname provides a 6 char truncated version of the release name.
*/ -}}
{{- define "mychart.shortname" -}}
{{ .Release.Name | trunc 6 }}
{{- end -}}
```

**良い例**(YAML コメント = デバッグ時に利用者へ見せたい警告):
```gotemplate
# This may cause problems if the value is more than 100Gi
memory: {{ .Values.maxMem | quote }}
```

**良い例**(`required` を含むブロックはテンプレートコメントで囲む):
```gotemplate
{{- /*
This may cause problems if the value is more than 100Gi
memory: {{ required "maxMem must be set" .Values.maxMem | quote }}
*/ -}}
```

**悪い例**(`required` の前に YAML コメント):
```gotemplate
# This may cause problems if the value is more than 100Gi
memory: {{ required "maxMem must be set" .Values.maxMem | quote }}
```

理由:
- テンプレートコメントは `helm template` の段階で完全に除去されるため、レンダリング結果を汚さない。defined テンプレートの解説などに最適。
- YAML コメントは `helm install --debug` で利用者の目に触れるため、利用者向けの警告(値の閾値、副作用の注意)を残したい場合に有効。
- `required` 関数は値が未定義のときにレンダリングを止めるが、YAML コメント内に書いた `{{ required ... }}` も評価対象になり、コメントのつもりがエラーの原因になる。

---

## JSON フロー形式の使用

YAML は JSON のスーパーセットであり、リスト・マップを `[...]` / `{...}` のフロー形式で書くこともできる。ただし読み手の認知負荷を一定に保つため、**JSON フロー形式は空コレクション(`[]` / `{}`)の表現に限り使用する**。要素を 1 つでも含むリスト・マップは、すべて YAML ブロック形式で記述する。

**良い例**:
```yaml
# 空コレクションはフロー形式
nodeSelector: {}
tolerations: []
podAnnotations: {}

# 要素ありはブロック形式
arguments:
  - "--dirname"
  - "/foo"

containerPorts:
  - name: http
    containerPort: 8080
    protocol: TCP
```

**悪い例**:
```yaml
# 要素ありをフロー形式で書いている
arguments: ["--dirname", "/foo"]

# さらに複雑な構造をフロー形式で書いている(可読性が崩壊)
containerPorts: [{name: http, containerPort: 8080, protocol: TCP}]

# 空コレクションをブロック形式で書こうとしている(YAML の書式上できない / 不自然)
nodeSelector:
tolerations:
```

理由:
- 「短いリストならフロー、長いならブロック」のような閾値ベースのルールは判断が主観的で、レビュアー間でブレる。
- 空を表現するブロック形式は存在しないため、空コレクションだけはフロー形式を許可せざるを得ない。これを唯一の例外と固定すれば、ルールが「**要素が 1 つでもあるか否か**」という機械的な判定になり、迷いが消える。
- 後から要素が増えたときに「フロー → ブロック」へ書き換える PR が発生せず、diff が安定する。
- helm-docs などの自動ツール出力や、添付テンプレート群の現状とも整合する。

---

## 外部設定ファイルの読み込み

`files/` ディレクトリ配下の外部設定ファイル(`rsyslog.conf`, `nginx.conf`, 初期化 SQL、TLS 証明書等)を ConfigMap / Secret に埋め込む際の読み込み方法は、ファイルの性質に応じて以下から選択する。`files/` ディレクトリ自体の配置ルールは `chart-files.md` を参照。

### 変数埋め込みが不要な場合: `.Files.Get`

ファイルの内容をそのまま読み込んで埋め込む。
```gotemplate
# templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-rsyslog
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
data:
  rsyslog.conf: |
    {{- .Files.Get "files/rsyslog.conf" | nindent 4 }}
```

### 変数埋め込みが必要な場合: `tpl` 関数でラップ

外部ファイル内に Helm テンプレート構文(`{{ .Values.syslog.server }}` 等)を記述したい場合、`tpl` 関数でラップしてレンダリングする。

**ただし、外部ファイル内に `{{` / `}}` 構文が登場しない場合に限る**。
```gotemplate
# templates/configmap.yaml
data:
  rsyslog.conf: |
    {{- tpl (.Files.Get "files/rsyslog.conf") . | nindent 4 }}
```

### 外部ファイルに `{{` / `}}` 構文が登場する場合

外部ファイル内の `{{` / `}}` には以下の 2 種類がある。レビュー時は外部ファイルの内容を確認し、どちらに該当するかを判別してから判定する。

#### Helm テンプレート構文として `tpl` で評価させる場合: 問題なし

外部ファイル内の `{{` / `}}` がすべて Helm テンプレート構文（`.Values.*`, `.Release.*`, `include`, `if`, `range` 等）であり、`tpl` で評価させることが意図である場合、`tpl (.Files.Get ...)` の使用は正当である。

```gotemplate
# files/app.conf — Helm テンプレート構文のみ
server_name = {{ .Values.app.serverName | quote }}
log_level = {{ .Values.app.logLevel }}
```
```gotemplate
# templates/configmap.yaml
data:
  app.conf: |
    {{- tpl (.Files.Get "files/app.conf") . | nindent 4 }}
```

#### 非 Helm のテンプレート構文を含む場合: インライン化

Grafana のアラートテンプレート（`{{ .alertname }}`）、Consul Template（`{{ key "..." }}`）、Go の `text/template` など、**Helm 以外のテンプレートエンジン向けの `{{` / `}}` 構文** が含まれる場合は、`tpl` が誤って解釈して構文衝突が発生する。この場合は外部ファイル化せず `templates/configmap.yaml` にインラインで記述する。

```gotemplate
# templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-grafana
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
data:
  datasources.yaml: |
    apiVersion: 1
    datasources:
      - name: Prometheus
        type: prometheus
        url: {{ .Values.prometheus.url | quote }}
```

理由:
- 非 Helm の `{{` / `}}` を含む外部ファイルを `tpl` に通すと、Helm が解釈しようとして構文衝突が発生する。エスケープで回避すると `{{ "{{" }}` のような記述が増えて可読性が著しく損なわれる。
- インラインなら構文衝突は発生せず、エスケープも不要。
- Helm テンプレート構文のみで構成された外部ファイルを `tpl` に通すのは `tpl` 関数の正当な使い方であり、違反ではない。

### 複数ファイルの一括読み込み: `.Files.Glob` + `.AsConfig`

`files/` 配下の複数ファイルを一括で ConfigMap に展開したい場合(初期化スクリプト群、複数の設定ファイル等)は、`.Files.Glob` と `.AsConfig` を使う。
```gotemplate
# templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-init-sql
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
data:
  {{- (.Files.Glob "files/init-sql/*.sql").AsConfig | nindent 2 }}
```

これで `files/init-sql/` 配下の全 `.sql` ファイルが、ファイル名をキーとした ConfigMap データ項目として自動展開される。

### バイナリデータ(証明書等): `b64enc`

TLS 証明書やバイナリデータを Secret に埋め込む場合は、`.Files.Get` の結果を `b64enc` でエンコードする。
```gotemplate
# templates/secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "myapp.fullname" . }}-tls
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
type: kubernetes.io/tls
data:
  tls.crt: {{ .Files.Get "files/tls/server.crt" | b64enc }}
  tls.key: {{ .Files.Get "files/tls/server.key" | b64enc }}
```

### 選択フローチャート
```
外部設定ファイルを配置するか?
  ├── No → templates/configmap.yaml にインラインで記述
  └── Yes
       │
       バイナリデータか?
       ├── Yes → .Files.Get | b64enc(Secret)
       └── No
            │
            複数ファイルを一括展開するか?
            ├── Yes → (.Files.Glob "...").AsConfig
            └── No
                 │
                 変数埋め込みが必要か?
                 ├── No → .Files.Get
                 └── Yes
                      │
                      外部ファイル内に {{ / }} が登場するか?
                      ├── Yes → インラインに切り替える
                      └── No  → tpl (.Files.Get "...") .
```