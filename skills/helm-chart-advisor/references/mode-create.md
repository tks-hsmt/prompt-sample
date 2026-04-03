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

ヒアリングで情報が揃ったら、作業着手前に構成全体の確認をユーザーに提示する。指定済み・未指定を問わず、すべての項目について挙動を明示し、認識を合わせる。

### 1. 構成一覧と挙動の説明

ヒアリング結果を整理し、各項目がどのような挙動になるかを説明する。指定済みの項目も含めて全体像を示す。

ユーザーが指定した項目も、デフォルトやベストプラクティスで自動適用される項目も、区別なくすべて含めること。どの項目も挙動の説明を必ず付ける。セキュリティ設定やリソース制限などユーザーが明示的に指定していない項目も省略せず、「何を防ぐのか」「何が起きるのか」を平易に説明する。

例:
```
■ 作成するチャートの構成

- チャート名: my-api
- ワークロード: Deployment（レプリカ数 1）
  → Pod が異常終了した場合は自動で再作成されます
- イメージ: node:20-alpine
- ポート: 3000
- ヘルスチェック: /health（liveness / readiness 両方）
  → アプリが応答しなくなった場合、自動で再起動されます
- Service: ClusterIP
  → クラスタ内部からのみアクセス可能です。外部公開が必要な場合は Ingress または LoadBalancer が必要です
- Ingress: 無効
  → ブラウザや外部クライアントから直接アクセスできません
- 永続ボリューム: なし
  → Pod の再起動でコンテナ内のデータは失われます
- HPA: 無効
  → アクセス増加時にPod数は自動で増えません。手動で replicaCount を変更する必要があります
- 依存チャート: なし
  → データベース等は別途デプロイ・管理が必要です
- リソース制限: requests (CPU: 100m, メモリ: 128Mi) / limits (CPU: 500m, メモリ: 256Mi)
  → 1つのPodがノードのリソースを使い切ることを防止します。アプリの特性に応じて調整してください
- 非root実行: runAsNonRoot: true, runAsUser/runAsGroup: 1000
  → コンテナは root 権限なしで動作します。万が一侵害されても被害範囲を限定できます
- 権限昇格の拒否: allowPrivilegeEscalation: false
  → コンテナ内で root 権限を取得する攻撃を防止します
- 読み取り専用ファイルシステム: readOnlyRootFilesystem: true
  → コンテナ内のファイル改ざんを防止します。一時ファイル用に /tmp を書き込み可能にマウントします
- ケーパビリティ全削除: capabilities.drop: ALL
  → 不要なLinux権限を除去し、攻撃面を最小化します
- seccomp プロファイル: RuntimeDefault
  → 危険なシステムコールをブロックします
- ServiceAccount: 専用アカウント自動作成、APIトークン自動マウント無効
  → Kubernetes APIへの不要なアクセスを防止します
```

### 2. 不整合チェック

構成全体を見て、パラメータ間の不整合や矛盾がないか確認する。不整合がある場合はユーザーに指摘し、解消方法を提案する。

よくある不整合の例:
- **外部公開が必要そうなのに Ingress も LoadBalancer も未指定**: 「REST API を外部から呼ぶ場合、Ingress か Service type: LoadBalancer が必要ですが、設定しますか？」
- **データベースを使うアプリなのに PVC も依存チャートもなし**: 「データの永続化が必要であれば、PVC を追加するか、DB を依存チャートとして追加する必要があります」
- **StatefulSet を指定しているのに PVC がなし**: 「StatefulSet は通常、永続データを扱うワークロード向けです。PVC は不要で間違いないですか？」
- **HPA を有効にしたのに resources の requests が未設定**: 「HPA は CPU/メモリの使用率で判断するため、resources.requests の設定が必須です」
- **ヘルスチェックのポートとアプリのポートが不一致**

### 3. 確認を求める

「この構成で作成を進めてよいですか？変更したい点があれば教えてください」と確認する。ユーザーの OK を得てから作業に着手する。

## 手順

1. `helm create <chart-name>` のスキャフォールドをベースにする
2. 以下の必須ファイルを整備する:
   - `Chart.yaml` — SemVer 2 バージョニング（詳細: `chart-structure.md`）
   - `values.yaml` — 合理的なデフォルト値、camelCase 命名、パラメータ名で始まるコメント（詳細: `values.md`）
   - `values.schema.json` — 入力バリデーション（詳細: `values.md`）
   - テンプレート群 — 1リソース1ファイル、kind を反映したファイル名（詳細: `templates.md`）
   - `templates/_helpers.tpl` — チャート名でプレフィックスした定義テンプレート
   - `templates/NOTES.txt` — インストール後の手順
3. セキュリティデフォルトを組み込む（詳細: `security.md`）
4. `helm lint` で検証する

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
