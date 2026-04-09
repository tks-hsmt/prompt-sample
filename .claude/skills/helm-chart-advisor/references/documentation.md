# ドキュメンテーションルール

本リファレンスは Helm チャートに含まれるユーザー向けドキュメント(`README.md`, `NOTES.txt`)の記述ルールについて記述します。

ドキュメンテーションの目的は、チャートの利用者(運用者・開発者)が以下を **チャートの中身を読まずに** 理解できるようにすることである。

- このチャートが何をデプロイするか
- どの値を設定する必要があるか
- インストール後に何を確認すべきか

---

## `README.md.gotmpl`(helm-docs テンプレート)

`README.md` は **手書きで管理しない**。`README.md.gotmpl` をテンプレートとして [helm-docs](https://github.com/norwoodj/helm-docs) で自動生成する。

### `README.md.gotmpl` の必須セクション

以下のセクションを最低限含むテンプレートとする。
```gotemplate
# {{ template "chart.name" . }}

{{ template "chart.description" . }}

{{ template "chart.versionBadge" . }}
{{ template "chart.appVersionBadge" . }}

## 概要

(チャートの目的・前提条件を手動で記述)

## 設定値

{{ template "chart.valuesTable" . }}

## メンテナ

{{ template "chart.maintainersSection" . }}
```

各テンプレート関数の役割:

| テンプレート関数 | 役割 |
|---|---|
| `chart.name` | `Chart.yaml` の `name` |
| `chart.description` | `Chart.yaml` の `description` |
| `chart.versionBadge` | チャートバージョンのバッジ |
| `chart.appVersionBadge` | アプリバージョンのバッジ |
| `chart.valuesTable` | `values.yaml` の `# --` コメントから自動生成された設定値の表 |
| `chart.maintainersSection` | `Chart.yaml` の `maintainers` セクション |

### `chart.valuesTable` の生成元

`chart.valuesTable` は `values.yaml` 内の `# --` プレフィックス付きコメントを読み取って設定値テーブルを自動生成する。`# --` コメントの記述ルール自体は `values.md` で定義しているため、本リファレンスではレビュー対象としない。

### 「概要」セクションの手動記述

`README.md.gotmpl` の中で **手動記述が必要なのは「概要」セクションのみ** とする。他のセクションは helm-docs の自動生成に任せる。

「概要」セクションには以下を最低限記述する。

- このチャートが何を(どのアプリケーションを)デプロイするか(1 文)
- 前提条件(対応 Kubernetes バージョン、依存リソース、必要な権限等)
- 環境別のデプロイ前提(`values-{env}.yaml` の存在に触れる)

**良い例**:
```markdown
## 概要

本チャートは社内ログ転送エージェント rsyslog を DaemonSet として全ノードに配置する。

### 前提条件

- Kubernetes 1.28 以降
- ノードに `/var/log` がマウントされていること
- 転送先 syslog サーバが稼働していること(`syslog.server` で指定)

### 環境別デプロイ

各環境への適用は、対応する `values-{env}.yaml` を `-f` で指定して `helm upgrade --install` を実行する。
```

**悪い例**(具体性がない):
```markdown
## 概要

このチャートは便利なアプリケーションをデプロイします。
```

### `README.md` の手動編集禁止

`README.md` は CI で自動生成したものを格納し、**手動編集を禁止する**。CI パイプライン上で以下を実行し、生成結果が既存ファイルと差分がある場合はビルドを失敗させる。
```bash
helm-docs --chart-search-root ./charts
git diff --exit-code charts/*/README.md
```

理由:
- `values.yaml` の `# --` コメントを唯一の真実の源(single source of truth)とすることで、値の説明と README が乖離しない。
- 手書き README は更新漏れが頻発するため、機械生成を強制する。
- CI でのチェックにより、README の更新漏れをビルド時に検出できる。

---

## `NOTES.txt`

`NOTES.txt` は `helm install` および `helm upgrade` 完了後に自動的に標準出力へ表示されるメッセージファイル。**運用者の初動を助けるための情報** を記述する。

### 必須記述項目

以下を最低限含める。

| 項目 | 例 |
|---|---|
| リリース名とチャート名の表示 | `Release "{{ .Release.Name }}" of chart "{{ .Chart.Name }}" has been deployed.` |
| 状態確認コマンド | `kubectl get pods -l app.kubernetes.io/instance={{ .Release.Name }} -n {{ .Release.Namespace }}` |
| アクセス方法 | Service / Ingress の有無に応じて場合分け |
| ログ確認コマンド | `kubectl logs -l app.kubernetes.io/instance={{ .Release.Name }} -n {{ .Release.Namespace }}` |

### 必須項目を満たした記述例
```gotemplate
# templates/NOTES.txt
{{- $name := include "myapp.fullname" . -}}
Release "{{ .Release.Name }}" of chart "{{ .Chart.Name }}" has been deployed to namespace "{{ .Release.Namespace }}".

1. Pod の状態を確認:
   kubectl get pods -l app.kubernetes.io/instance={{ .Release.Name }} -n {{ .Release.Namespace }}

2. アプリケーションログを確認:
   kubectl logs -l app.kubernetes.io/instance={{ .Release.Name }} -n {{ .Release.Namespace }} --tail=100

3. アプリケーションへのアクセス:
{{- if .Values.ingress.enabled }}
   {{- range $host := .Values.ingress.hosts }}
   {{- range .paths }}
   https://{{ $host.host }}{{ .path }}
   {{- end }}
   {{- end }}
{{- else if .Values.service.enabled }}
   kubectl port-forward svc/{{ $name }} 8080:{{ .Values.service.port }} -n {{ .Release.Namespace }}
   その後、http://localhost:8080 にアクセスする。
{{- else }}
   このチャートは外部公開エンドポイントを持たない。
{{- end }}
```

### 空ファイルでの提出禁止

`NOTES.txt` を空ファイルのまま提出してはならない。最低でも上記の必須記述項目を含むこと。

理由:
- `NOTES.txt` はインストール直後にユーザーの目に確実に触れる唯一のドキュメントである。空だと「インストールが成功したのか?」「次に何をすればよいか?」が不明瞭になる。
- インシデント発生時の初動(状態確認・ログ確認)で `NOTES.txt` が手順書代わりになる。

### 機密情報の出力禁止

`NOTES.txt` には以下の情報を **出力してはならない**。

- パスワード、API キー、トークン
- 秘密鍵、証明書の中身
- 接続文字列(認証情報を含むもの)

理由:
- `NOTES.txt` の出力は CI/CD ログ、ターミナル履歴、`helm get notes` の結果など、複数の場所に残る。
- 機密情報を表示する代わりに「`kubectl get secret <name> -o jsonpath='{.data.password}' | base64 -d` で取得できる」のような取得方法を案内する。

**悪い例**:
```gotemplate
データベースパスワード: {{ .Values.database.password }}
```

**良い例**:
```gotemplate
データベースパスワードは Secret から取得する:
   kubectl get secret {{ include "myapp.fullname" . }}-db -o jsonpath='{.data.password}' -n {{ .Release.Namespace }} | base64 -d
```

---

## 参考

- helm-docs: https://github.com/norwoodj/helm-docs