# 新規作成モード

ユーザーが新しい Helm chart を作成したい場合の手順。

## ヒアリング

作業を始める前に、以下の情報がユーザーの依頼から読み取れるか確認する。不足している項目があれば、作業に着手せずまとめてヒアリングする。すでに明示されている項目は聞き直さない。

**必須（不明なら必ず確認）:**
- **チャート名**: どんな名前にするか（命名規則に沿った名前を提案してもよい）
- **ワークロードの種類**: Deployment / DaemonSet / StatefulSet / CronJob のどれか
- **コンテナイメージ**: 使用するイメージとタグ（まだ決まっていなければプレースホルダでよいか確認）
- **公開ポート**: アプリケーションがリッスンするポート番号
- **ヘルスチェック**: エンドポイントのパスとポート（例: /health:3000）。ヘルスチェックの仕組みがない場合は TCP や exec も検討

**任意（依頼に含まれていなければデフォルトで進めてよい。ただし想定と異なる可能性がある場合は軽く確認）:**
- **Service の種類**: ClusterIP / NodePort / LoadBalancer（デフォルト: ClusterIP）
- **Ingress の要否**: 外部公開が必要か（デフォルト: 無効）
- **永続ボリューム**: PVC が必要か（デフォルト: なし）
- **依存チャート**: PostgreSQL, Redis 等の依存があるか（デフォルト: なし）
- **環境変数・ConfigMap**: アプリに渡す設定値があるか
- **オートスケーリング**: HPA が必要か（デフォルト: 無効）

明らかに推測できる項目（例: 「Node.js API」と言われたら Deployment がほぼ確実）は確認不要。回答の中で新たな不明点が出てきたら追加で確認してよい。

## 構成確認

`confirmation-rules.md` のルールに従い、構成全体の確認をユーザーに提示する。新規作成では全項目（ワークロード、Service、Ingress、セキュリティ設定等）を対象に行う。

## 手順

1. **ヒアリング**: 上記のヒアリング項目に基づき、不足情報を確認する
2. **構成確認**: 上記の構成確認に基づき、全項目の挙動説明・不整合チェックを行い、ユーザーの OK を得る
3. **プラン出力**: 確認済みの構成内容を `result/helm-chart-advisor-create-plan-{yyyyMMddHHmm}.md` に保存する。ファイルには構成一覧（挙動説明付き）、不整合チェック結果、ユーザーとの合意事項を含める
4. **プランに基づいて作成**: 手順3で出力したプランファイルをインプットとして、以降の作業を行う。`helm create <chart-name>` のスキャフォールドをベースにする
5. 以下の必須ファイルを整備する:
   - `Chart.yaml` — SemVer 2 バージョニング（詳細: `chart-structure.md`）
   - `values.yaml` — 合理的なデフォルト値、camelCase 命名、パラメータ名で始まるコメント（詳細: `values.md`）
   - `values.schema.json` — 入力バリデーション（詳細: `values.md`）
   - テンプレート群 — 1リソース1ファイル、kind を反映したファイル名（詳細: `templates.md`）
   - `templates/_helpers.tpl` — チャート名でプレフィックスした定義テンプレート
   - `templates/NOTES.txt` — インストール後の手順
6. セキュリティデフォルトを組み込む（詳細: `security.md`）
7. `helm lint` で検証する

## values.yaml のテンプレートパターン

チャート作成時、以下の構造を values.yaml のベースとして使う:

```yaml
# replicaCount はデプロイメントのレプリカ数
replicaCount: 1

# image はコンテナイメージの設定
image:
  # image.repository はコンテナイメージのリポジトリ
  repository: nginx
  # image.tag はコンテナイメージのタグ（未指定時は Chart.yaml の appVersion を使用）
  tag: ""
  # image.pullPolicy はイメージの取得ポリシー
  pullPolicy: IfNotPresent

# resources はCPU/メモリのリクエストとリミット
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 256Mi

# podSecurityContext はPodレベルのセキュリティコンテキスト
podSecurityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
  seccompProfile:
    type: RuntimeDefault

# containerSecurityContext はコンテナレベルのセキュリティコンテキスト
containerSecurityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  runAsUser: 1000
  capabilities:
    drop:
      - ALL

# serviceAccount はServiceAccountの設定
serviceAccount:
  # serviceAccount.create はServiceAccountを作成するかどうか
  create: true
  # serviceAccount.name はServiceAccountの名前（空の場合は自動生成）
  name: ""
  # serviceAccount.automountToken はAPIトークンを自動マウントするかどうか
  automountToken: false

# networkPolicy はNetworkPolicyの設定
networkPolicy:
  # networkPolicy.enabled はNetworkPolicyを作成するかどうか
  enabled: false
```

## セキュリティコンテキストのテンプレート例

deployment.yaml での展開パターン:

```yaml
spec:
  template:
    spec:
      securityContext:
        {{- toYaml .Values.podSecurityContext | nindent 8 }}
      containers:
        - name: {{ .Chart.Name }}
          securityContext:
            {{- toYaml .Values.containerSecurityContext | nindent 12 }}
```

## 関連リファレンス

新規作成時に確認すべきリファレンス:
- `chart-structure.md` — 命名規則、バージョニング
- `values.md` — values 設計、スキーマ
- `templates.md` — テンプレート構造
- `security.md` — セキュリティ設定
- `workloads.md` — イメージ、リソース、プローブ、ラベル
