# コンテナイメージの指定方法

## 固定タグまたはSHAダイジェストの使用

**設定内容**: `latest`、`head`、`canary` などのフローティングタグを使用せず、固定タグ（例: `1.25.3`）または SHA ダイジェスト（例: `nginx@sha256:abc123...`）を使用する。

**目的と効果**: デプロイの再現性を保証する。同じ values で `helm install` すれば、いつでも同じコンテナイメージが pull される。SHA ダイジェストによりタグの上書き攻撃も防止できる。

**ユースケース**: CI/CD パイプラインでビルドしたイメージに Git コミット SHA をタグとして付与し、`--set image.tag=$GITHUB_SHA` でデプロイする。

## イメージ定義の values 分離

**設定内容**: `image.repository`、`image.tag`、`image.pullPolicy` を個別の values キーとして定義し、テンプレートでは `"{{ .Values.image.repository }}:{{ .Values.image.tag }}"` のように参照する。

**目的と効果**: イメージの差し替え（レジストリ移行、バージョンアップ）をテンプレート変更なしで行える。`pullPolicy` も環境ごとに制御可能にする（開発: `Always`、本番: `IfNotPresent`）。

---

# リソースリミットとヘルスチェック

## CPU/メモリの requests と limits

**設定内容**: すべてのコンテナに `resources.requests` と `resources.limits` を明示的に設定する。

```yaml
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 256Mi
```

**目的と効果**: `requests` はスケジューラがPodの配置先ノードを決定する際に使用され、`limits` はコンテナが使用できるリソースの上限を設定する。未設定の場合、1つのPodがノード上の全リソースを消費するリソース枯渇状態を引き起こす可能性がある。

## liveness / readiness / startup probes

**設定内容**: `livenessProbe`（コンテナの再起動判定）、`readinessProbe`（トラフィック受信判定）、`startupProbe`（起動完了判定）を定義する。

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: http
  initialDelaySeconds: 30
  periodSeconds: 10
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /ready
    port: http
  initialDelaySeconds: 5
  periodSeconds: 5

startupProbe:
  httpGet:
    path: /healthz
    port: http
  failureThreshold: 30
  periodSeconds: 10
```

**目的と効果**: liveness probe の失敗でコンテナが自動再起動され、デッドロック等からの回復が可能になる。readiness probe の失敗で Service のエンドポイントから除外され、ユーザーへのエラー応答が防止される。startup probe は起動が遅いアプリケーション（JVM、大規模DB等）で liveness probe による早期 kill を防止する。

---

# ラベルとアノテーションの標準化

## 推奨ラベルの使用

**設定内容**: Kubernetes の推奨ラベル（`app.kubernetes.io/*`）を使用する。

| ラベル | 区分 | 用途 |
|---|---|---|
| `app.kubernetes.io/name` | REC | アプリケーション名 |
| `app.kubernetes.io/instance` | REC | リリースインスタンス名 |
| `app.kubernetes.io/version` | REC | アプリケーションバージョン |
| `app.kubernetes.io/component` | OPT | コンポーネント識別 |
| `app.kubernetes.io/part-of` | OPT | 上位アプリケーション名 |
| `app.kubernetes.io/managed-by` | REC | 管理ツール（Helm） |

## セレクターの設計

**設定内容**: `selector.matchLabels` には不変のラベル（`app.kubernetes.io/name` と `app.kubernetes.io/instance`）のみを指定し、`version` やリリース日のように変化するラベルは含めない。

**目的と効果**: Deployment の selector は一度作成すると変更不可（immutable）であるため、変動するラベルを含めるとアップグレード時に「selector does not match」エラーが発生する。

