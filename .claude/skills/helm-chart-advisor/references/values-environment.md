# 環境別 values ファイルルール

本ドキュメントは環境別の values オーバーライドファイル(`values-dev.yaml` / `values-stg.yaml` / `values-prod.yaml`)の作成ルールを定める。チャート全体のファイル構成は `chart-files.md` を参照。

本ルールの対象はチャート作成者が作成するファイル自体の構成と記述内容であり、`helm install` / `helm upgrade` のデプロイ手順は対象外とする。

---

## 環境名と必須ファイル

環境名は **`dev` / `stg` / `prod` の 3 つに固定** する。それ以外の環境名(`qa`, `preview`, `perf` 等)の追加は禁止する。

すべてのチャートで以下 3 ファイルを **必ず作成する** 必要がある。1 つでも欠けている場合、CI でのファイル存在チェックで拒否する。

| ファイル | 対応環境 |
|---|---|
| `values-dev.yaml` | 開発環境 |
| `values-stg.yaml` | ステージング環境 |
| `values-prod.yaml` | 本番環境 |

### 配置場所

3 ファイルは `values.yaml` と **同一階層**(チャートルート直下)に配置する。サブディレクトリ(`environments/` 等)には置かない。
```
myapp/
├── Chart.yaml
├── values.yaml              # ベース値(全環境共通のデフォルト)
├── values-dev.yaml          # dev オーバーライド
├── values-stg.yaml          # stg オーバーライド
└── values-prod.yaml         # prod オーバーライド
```

---

## ファイル内容の原則

環境別 values ファイルは **差分だけを記述する**。`values.yaml` の内容を丸ごとコピーしてはならない。

### 良い例(差分のみ)
```yaml
# values-prod.yaml
replicaCount: 3

resources:
  requests:
    cpu: 500m
    memory: 512Mi
  limits:
    cpu: 1000m
    memory: 1Gi

autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 10

podDisruptionBudget:
  enabled: true
  minAvailable: 2
```

### 悪い例(values.yaml の全コピー)
```yaml
# values-prod.yaml
image:
  repository: "123456789012.dkr.ecr.ap-northeast-1.amazonaws.com/myapp"
  pullPolicy: IfNotPresent
  digest: ""
component: web
nameOverride: ""
fullnameOverride: ""
serviceAccount:
  create: true
  # ... 以下 200 行、values.yaml の内容をそのままコピー
```

理由:
- 差分だけにすることで、各環境でどの値を変えているかが一目で分かる。
- `values.yaml` のデフォルト値を変更したとき、環境別ファイルが自動的に追従する。全コピーしていると環境ごとに手動更新が必要になり、更新漏れが発生する。
- レビュー時の認知負荷が下がる。

---

## オーバーライド内容

以下のキーは `values-dev.yaml` / `values-stg.yaml` / `values-prod.yaml` で必ず値を上書きする。

| キー | 理由 |
|---|---|
| `replicaCount` | 環境ごとに台数を変更可能とする |
| `image.repository` | 環境別にリポジトリが異なるため |
| `resources.requests` | 環境のトラフィック量に応じて変える |
| `resources.limits` | 同上 |

その他のキーについては必要に応じてオーバーライドする。