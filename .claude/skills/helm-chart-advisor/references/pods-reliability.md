# Pod 信頼性ルール(リソース / プローブ / HA 配置)

本リファレンスではPod の信頼性・可用性に関するルールについて記述します。

---

## リソース要求と制限

すべてのコンテナで以下 **4 項目をすべて必須** とする。未指定は `values.schema.json` で拒否する。

| フィールド | 必須 | 備考 |
|---|---|---|
| `resources.requests.cpu` | 必須 | |
| `resources.requests.memory` | 必須 | |
| `resources.limits.cpu` | 必須 | |
| `resources.limits.memory` | 必須 | |

**良い例**:
```yaml
# values.yaml
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 128Mi
```

**悪い例**:
```yaml
# requests と limits のどちらかが欠けている
resources:
  requests:
    cpu: 100m
    memory: 128Mi
```
```yaml
# CPU の指定がない
resources:
  requests:
    memory: 128Mi
  limits:
    memory: 128Mi
```

理由:
- `requests` がないと、Kubernetes スケジューラは Pod のリソース需要を知らないまま配置を決める。ノードに過剰な Pod がスケジュールされ、メモリ枯渇で OOMKill の連鎖が発生しうる。
- `limits` がないと、1 Pod がノード全体のリソースを占有してノイジーネイバー問題を引き起こす。
- QoS クラス(Guaranteed / Burstable / BestEffort)を明示的に制御するためにも、全項目の指定が必要である。

### メモリの requests / limits 比率(推奨)

**メモリは `requests == limits` とすることを推奨する**。

理由:
- メモリは圧縮不可リソース(CPU と違って throttling できない)。limits を requests より大きく設定すると、limits 以下 / requests 以上のメモリ使用時に「ノードに空きがあれば使えるが、空きがなければ OOMKill される」という確率的な挙動になる。
- `requests == limits` とすれば QoS が Guaranteed クラスになり、ノードのメモリ逼迫時に最優先で保護される。
- ただし具体値はアプリの特性と要件で決まるため、本ルールでは強制せず推奨レベルとする。

### CPU の requests / limits 比率(要件で決定)

CPU limits の値は要件で決まるため具体値は規定しない。以下のトレードオフを理解した上で決定すること。

- `requests == limits`: バーストが効かず性能が出にくいが、挙動が安定する
- `limits > requests * 2` 程度: バーストを許容し、ノードの空きリソースを活用できる
- CPU throttling の挙動を理解すること(CFS quota により limits を超えた CPU 使用は強制的に待たされる)

---

## プローブ

### livenessProbe

長時間稼働するワークロード(Deployment / StatefulSet / DaemonSet)では **`livenessProbe` を必須とする**。Job / CronJob では任意(短命のため通常不要)。

### readinessProbe

**Service が紐づくワークロード**(`service.enabled: true`)では **`readinessProbe` を必須とする**。

### startupProbe(任意)

`startupProbe` は **任意** とする。ただし、起動に時間がかかるアプリケーション(Java Spring Boot, Rails, 大きなデータセットをロードする ML 推論サーバ等)で使用する場合は、以下の注意事項に従うこと。

**startupProbe を設定する場合の注意事項**:

- `startupProbe` が成功するまで `livenessProbe` と `readinessProbe` の実行は抑制される。このため、`livenessProbe.initialDelaySeconds` を大きくする必要がなくなる(`0` 設定可)
- `startupProbe.failureThreshold × startupProbe.periodSeconds` が **アプリの最大起動時間** となる。この値が短すぎると起動中に failing 判定されて再起動ループに入る
- 推奨設定例: `failureThreshold: 30`, `periodSeconds: 10`(最大 5 分の起動時間を許容)
- `startupProbe` と `livenessProbe` は同じエンドポイントで構わないが、別エンドポイントにして起動完了判定と運用ヘルスチェックを分離する設計も可
- 起動が速いアプリ(Go バイナリ、静的コンテンツサーバ等)には不要。設定すると冗長なチェックが 1 つ増えるだけでメリットがない

### プローブパラメータの明示

すべてのプローブで以下のパラメータを **明示的に指定する**。Kubernetes のデフォルト値に依存しない。

| パラメータ | 推奨値 | 備考 |
|---|---|---|
| `periodSeconds` | `10` | プローブ実行間隔 |
| `timeoutSeconds` | `5` | 1 回のプローブのタイムアウト(デフォルト 1 秒は事故の元) |
| `failureThreshold` | `3` | 連続失敗回数の閾値 |
| `successThreshold` | `1` | `livenessProbe` / `startupProbe` では必ず 1 |
| `initialDelaySeconds` | `startupProbe` 使用時は `0`、未使用時はアプリ起動時間+余裕 | |

理由(明示化の意図):
- Kubernetes のデフォルト `timeoutSeconds: 1` は、JIT コンパイルやネットワーク揺らぎで頻繁に超過し、健全な Pod が failing 判定されて再起動ループに入る事故を起こしやすい。本ルールでは `5` 秒を最低ラインとする。
- Kubernetes デフォルトは将来のバージョンで変わる可能性があり、バージョン間の挙動差を防ぐために明示する。
- レビュー時に「書いていない値が意図的なのか書き忘れなのか」を区別できる。

**良い例**:
```yaml
# values.yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: http
  initialDelaySeconds: 0        # startupProbe を使うため 0
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
  successThreshold: 1

readinessProbe:
  httpGet:
    path: /ready
    port: http
  initialDelaySeconds: 0
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
  successThreshold: 1

startupProbe:
  enabled: true                 # 起動が遅い Java アプリ
  httpGet:
    path: /healthz
    port: http
  periodSeconds: 10
  failureThreshold: 30          # 最大 5 分の起動時間を許容
  timeoutSeconds: 5
```

**悪い例**:
```yaml
# パラメータ省略 → K8s デフォルトに依存
livenessProbe:
  httpGet:
    path: /healthz
    port: http
  # periodSeconds, timeoutSeconds, failureThreshold が未指定
  # → timeoutSeconds: 1 で頻繁にタイムアウトして再起動ループ
```

---

## グレースフルシャットダウン

### terminationGracePeriodSeconds

`terminationGracePeriodSeconds` の既定値は **30 秒** とする。長時間処理を持つワークロード(バッチジョブ、gRPC ストリーミング等)では values で上書き可能とする。
```yaml
# values.yaml
terminationGracePeriodSeconds: 30
```

### preStop フック

**Service が紐づくワークロード(`service.enabled: true`)を持つチャートテンプレートでは、`lifecycle.preStop.sleep.seconds` を既定値 `5` 秒で必須とする**。Job / CronJob チャートテンプレートでは任意とする。

これは HTTP / TCP / WebSocket 等、**プロトコルに依存しない Endpoint 伝搬遅延対策** である。

**良い例**:
```yaml
# values.yaml (Service 紐付きワークロード)
lifecycle:
  preStop:
    sleep:
      seconds: 5
terminationGracePeriodSeconds: 30  # preStop の 5 秒を含めてこれ以上にする
```
```gotemplate
# templates/deployment.yaml
containers:
  - name: {{ .Chart.Name }}
    lifecycle:
      preStop:
        sleep:
          seconds: {{ .Values.lifecycle.preStop.sleep.seconds }}
```

**悪い例**:
```yaml
# Service 紐付きなのに preStop がない
service:
  enabled: true
# lifecycle の指定なし → schema 違反
```

理由:
- Pod が削除されるとき、Kubernetes は以下の 2 つを並列に実行する:
  1. `kubelet` がコンテナに `SIGTERM` を送る
  2. `kube-proxy` / Ingress コントローラが Service の Endpoint から Pod を削除する
- 2 の Endpoint 伝搬は 1 より遅れるため、シャットダウン中の Pod にロードバランサからのトラフィックが流れ続け、接続エラーが発生する。
- `preStop.sleep` を挟むことで、アプリが `SIGTERM` を受ける前に Endpoint 伝搬が完了するまで待たせられる。
- 5 秒は実測ベースの安全マージンで、kube-proxy の更新間隔(デフォルト 30 秒の iptables sync)を完全にカバーはしないが、多くの Ingress コントローラ(ALB, NGINX Ingress 等)の Endpoint 反映時間としては十分。

### gRPC / DB ワークロード(推奨)

**gRPC サーバおよび StatefulSet の DB ワークロードでは、`preStop.sleep` に加えて、アプリ側で SIGTERM ハンドラを実装することを推奨する**(チャートでは強制しない)。

- gRPC サーバ: `GOAWAY` フレームを送信して既存接続に新規リクエストが来ないよう通知する
- DB: トランザクションの完了を待ってからコネクションをクローズする

---

## HA 配置

### topologySpreadConstraints

**`replicaCount >= 2` のワークロードでは `topologySpreadConstraints` を必須とする**。AZ とノードの 2 レベルで分散配置する。

| パラメータ | 値 |
|---|---|
| `topologyKey`(1 つ目) | `topology.kubernetes.io/zone` |
| `topologyKey`(2 つ目) | `kubernetes.io/hostname` |
| `maxSkew` | `1` |
| `whenUnsatisfiable` | `ScheduleAnyway` |
| `labelSelector` | `selectorLabels` と同じラベルセット |

**良い例**:
```yaml
# values.yaml
replicaCount: 3
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        # selectorLabels と同じ内容(テンプレートで展開)
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        # selectorLabels と同じ内容
```
```gotemplate
# templates/deployment.yaml
spec:
  template:
    spec:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              {{- include "myapp.selectorLabels" . | nindent 14 }}
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              {{- include "myapp.selectorLabels" . | nindent 14 }}
```

**悪い例**(`DoNotSchedule` を指定):
```yaml
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: DoNotSchedule     # ノード不足時に Pending になる
```

理由:
- EKS では複数 AZ にノードがあるのが通常構成であり、AZ 障害時に全 Pod が同時停止しないようにするためには AZ 分散が必須。
- AZ 分散だけでなくノード分散も必要。同一ノードに全レプリカが配置されると、ノード退避(EKS Managed Node Group の更新等)で全レプリカが同時に移動する。
- `whenUnsatisfiable: ScheduleAnyway` にすることで、「できる限り分散するが、ノード不足なら妥協する」挙動となり、Pending による可用性低下を避けつつ HA を実現できる。`DoNotSchedule` は厳格だが、ノード不足時に Pod が起動できなくなるリスクがある。
- `labelSelector` は必ず `selectorLabels`(不変ラベルのみ)と一致させる。`labels`(可変ラベル含む)を使うと、`helm upgrade` 時にセレクタが変わって分散制約が機能しない瞬間が発生する。

出典: https://kubernetes.io/docs/concepts/scheduling-eviction/topology-spread-constraints/

### PodDisruptionBudget

**Deployment / StatefulSet で `replicaCount >= 2` のワークロードでは `PodDisruptionBudget` を必須とする**。DaemonSet / Job / CronJob では PDB を使用しない。values では `podDisruptionBudget.enabled: true` を既定とし、`minAvailable` を指定する。

**良い例**:
```yaml
# values.yaml
replicaCount: 3
podDisruptionBudget:
  enabled: true
  minAvailable: 2              # 3 レプリカ中 2 つは常に稼働
```
```gotemplate
# templates/pdb.yaml
{{- if and .Values.podDisruptionBudget.enabled (ge (int .Values.replicaCount) 2) }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "myapp.fullname" . }}
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  minAvailable: {{ .Values.podDisruptionBudget.minAvailable }}
  selector:
    matchLabels:
      {{- include "myapp.selectorLabels" . | nindent 6 }}
{{- end }}
```

**悪い例**(`replicaCount: 2` で `minAvailable: 2`):
```yaml
replicaCount: 2
podDisruptionBudget:
  enabled: true
  minAvailable: 2              # 退避時に 1 Pod も退避できず、ノード更新が詰まる
```

理由:
- PDB は `kubectl drain` や Cluster Autoscaler によるノード退避時に、同時に停止される Pod 数を制限する。
- PDB なしでノード退避が発生すると、同じノード上のレプリカが一度に全滅する可能性がある。
- `minAvailable` はレプリカ数より小さく設定する(同値にするとノード退避が永久にブロックされる)。目安: `replicaCount - 1`。
- `maxUnavailable` 指定も可能だが、`minAvailable` の方が「最低限動き続ける数」として直感的で、レプリカ数変更時に調整が不要な場合が多い。
- DaemonSet は各ノードに 1 Pod ずつ配置される性質上、PDB で「最低 N 台を維持」という制御は意味をなさない。DaemonSet のローリング更新時の可用性は `updateStrategy.rollingUpdate.maxUnavailable` フィールドで制御する。
- Job / CronJob は短命なワークロードで、退避時に守るべき可用性の概念がない。
