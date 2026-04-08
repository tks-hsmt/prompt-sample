# Helm Chart 作成計画: rsyslog-receiver

## 概要

通信装置からシスログを受信する rsyslog Pod を Deployment として作成する。
受信したメッセージが RFC5424 形式に準拠しているかを rsyslog のルールセットで判定し、
準拠している場合は後続の fluentd へ TCP 転送、非準拠の場合は破棄する。

## チャート基本情報

| 項目 | 値 |
|---|---|
| チャート名 | `rsyslog-receiver` |
| ワークロード種別 | Deployment |
| コンテナイメージ | `docker.io/rsyslog/syslog_appliance_alpine` (digest はデプロイ時に指定) |
| appVersion | `"8.2404.0"` |

## ディレクトリ構成

```
rsyslog-receiver/
├── .helmignore
├── Chart.yaml
├── values.yaml
├── values.schema.json
├── values-dev.yaml
├── values-stg.yaml
├── values-prod.yaml
├── README.md.gotmpl
├── README.md
├── files/
│   └── rsyslog.conf
└── templates/
    ├── _helpers.tpl
    ├── NOTES.txt
    ├── deployment.yaml
    ├── service.yaml
    ├── serviceaccount.yaml
    └── configmap.yaml
```

## rsyslog 設定方針

`files/rsyslog.conf` に rsyslog の設定ファイルを配置し、ConfigMap 経由でコンテナにマウントする。
設定ファイル内に Helm テンプレート変数を埋め込み、`tpl` 関数でレンダリングする。

### 処理フロー

1. `imudp` / `imtcp` モジュールでコンテナポート 1514 にて syslog を受信
2. カスタムルールセット `rfc5424check` で受信メッセージを評価
3. `$protocol-version == "1"` (RFC5424) の場合 → `omfwd` で fluentd へ TCP 転送
4. それ以外 (RFC3164 等) → `stop` で破棄

### ポート設計

| 用途 | コンテナポート | Service ポート | プロトコル |
|---|---|---|---|
| syslog 受信 (UDP) | 1514 | 514 | UDP |
| syslog 受信 (TCP) | 1514 | 514 | TCP |

コンテナポートを 1514 (非特権ポート) にすることで `NET_BIND_SERVICE` ケーパビリティが不要。
Service が 514 → 1514 にマッピングするため、通信装置側は標準ポート 514 で送信可能。

## values.yaml 主要キー

```yaml
# -- イメージリポジトリ
image:
  repository: "docker.io/rsyslog/syslog_appliance_alpine"
  digest: ""
  pullPolicy: IfNotPresent

# -- コンポーネント名
component: "syslog-receiver"

# -- レプリカ数
replicaCount: 1

# -- syslog 受信設定
syslog:
  port: 1514

# -- 転送先 fluentd 設定
forwarder:
  target: "fluentd.logging.svc.cluster.local"
  port: 24224

# -- Service 設定 (UDP)
service:
  type: LoadBalancer
  port: 514
  containerPort: 1514
  portName: "syslog-udp"
  protocol: UDP

# -- ConfigMap 自動生成
config:
  enabled: true

# -- リソース
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 256Mi

# -- Pod セキュリティコンテキスト
podSecurityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
  seccompProfile:
    type: RuntimeDefault

# -- コンテナセキュリティコンテキスト
containerSecurityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  allowPrivilegeEscalation: false
  privileged: false
  readOnlyRootFilesystem: true
  capabilities:
    drop:
      - ALL

# -- プローブ (TCP チェック)
livenessProbe:
  tcpSocket:
    port: syslog-tcp
  initialDelaySeconds: 10
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
  successThreshold: 1

readinessProbe:
  tcpSocket:
    port: syslog-tcp
  initialDelaySeconds: 5
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
  successThreshold: 1

startupProbe:
  enabled: false

# -- ServiceAccount
serviceAccount:
  create: true
  name: ""
  annotations: {}
  automountToken: false

# -- RBAC (K8s API 不要)
rbac:
  create: false

# -- preStop / terminationGracePeriodSeconds
lifecycle:
  preStop:
    sleep:
      seconds: 5
terminationGracePeriodSeconds: 30
```

## 環境別オーバーライド方針

### values-dev.yaml
- `replicaCount: 1`
- `image.repository`: 開発用リポジトリ (プレースホルダ)
- `resources`: 最小構成 (100m/128Mi)
- `service.type: ClusterIP` (開発環境は外部公開不要)

### values-stg.yaml
- `replicaCount: 1`
- `image.repository`: ステージング用リポジトリ (プレースホルダ)
- `resources`: 中間構成 (200m/256Mi)
- `service.type: LoadBalancer`

### values-prod.yaml
- `replicaCount: 2`
- `image.repository`: 本番用リポジトリ (プレースホルダ)
- `resources`: 本番構成 (500m/512Mi)
- `service.type: LoadBalancer`

## セキュリティ設定

- 非 root 実行 (UID/GID 1000)
- `readOnlyRootFilesystem: true` (/tmp と rsyslog ワークディレクトリは emptyDir マウント)
- `capabilities.drop: ["ALL"]` (NET_BIND_SERVICE 不要)
- `seccompProfile.type: RuntimeDefault`
- `automountServiceAccountToken: false`
- `allowPrivilegeEscalation: false`

## 特記事項

1. **Service の複数ポート対応**: syslog は UDP/TCP 両方で受信するため、Service テンプレートで UDP と TCP の 2 ポートを定義する。values の `service.*` は UDP 用の標準キーを使い、TCP ポートはテンプレート内で同一ポート番号を使って追加する。
2. **rsyslog ワークディレクトリ**: rsyslog はワークディレクトリ (`/var/lib/rsyslog`) への書き込みが必要。`readOnlyRootFilesystem: true` のため emptyDir をマウントする。
3. **image.digest**: デフォルト値は空文字。デプロイ時に必ず指定すること (`values.schema.json` で必須化)。
4. **forwarder / syslog キー**: アプリ固有の設定として標準キー一覧外のキーを追加。
