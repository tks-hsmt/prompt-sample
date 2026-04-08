# ワークロード基礎: DaemonSet

全ノードまたは選択したノード群に **1 ノード 1 Pod** で配置するワークロード。ノードレベルのインフラ (ログ収集、メトリクス収集、CNI、ストレージプラグイン、syslog 受信等) で使用。

## 該当するアプリの典型例

- ログ収集 (fluentd, fluent-bit, vector, filebeat 等)
- メトリクス収集 (node-exporter, datadog-agent, telegraf 等)
- syslog 受信 (rsyslog, syslog-ng 等)
- CNI プラグイン (calico-node, cilium-agent 等)
- ストレージプラグイン (csi-driver-node 等)
- セキュリティエージェント (falco 等)

## DaemonSet 固有パラメータ

| パラメータ | デフォルト | 意味 |
|---|---|---|
| `updateStrategy.type` | `RollingUpdate` | 更新戦略 |
| `updateStrategy.rollingUpdate.maxUnavailable` | `1` | 同時更新可能ノード数 |
| `updateStrategy.rollingUpdate.maxSurge` | `0` (バージョン依存あり) | 同一ノード上の新旧並行 |
| `hostNetwork` | `false` | ホストネットワーク使用 |
| `hostPID` | `false` | ホスト PID 名前空間使用 |

### `updateStrategy.type`

| 値 | 挙動 |
|---|---|
| **`RollingUpdate`** (k8s 既定) | 各ノードの旧 Pod を段階的に新 Pod に置換 |
| `OnDelete` | テンプレート更新後、手動 Pod 削除で再作成。段階的検証用 |

### `hostNetwork` / `hostPID`

| 値 | 影響 |
|---|---|
| `false` (k8s 既定、推奨) | 通常の Pod ネットワーク / PID 名前空間 |
| `true` | ホストの名前空間を共有。**Pod Security Standards Baseline/Restricted で禁止**。CNI、ノード監視等の特殊用途のみ |

---

## DaemonSet での能動的提案 (重要)

DaemonSet ワークロード確定時、Claude は以下を **必ず能動的に提案** する。受動的に「未設定」 のまま残さない。

### 1. PriorityClassName (能動提案必須)

DaemonSet の用途は多くがノードレベルのインフラ (ログ収集、メトリクス、CNI 等) で、ノード上で確実に動いてほしいもの。リソース不足時に preempt されるべきではない。

**能動提案**:
- **ログ収集 / メトリクス収集 / 重要インフラ**: 専用の高優先度 PriorityClass (組織で定義済みなら) を推奨。組織標準がなければ作成を提案
- **`system-cluster-critical` / `system-node-critical`**: これらは k8s が予約している。ユーザーアプリケーションには通常使わない (公式ドキュメントでも控えめな推奨)。本当にクラスタ存続に必須な場合のみ
- **重要度が低い場合**: デフォルト優先度のまま OK

**質問例**:
> 「このログ収集 DaemonSet はノード上で確実に動いてほしいインフラです。組織で定義済みの高優先度 PriorityClass はありますか? なければ、`system-node-critical` を使うか、専用 PriorityClass を作成することを推奨します」

### 2. tolerations (能動提案必須)

デフォルトでは taint されたノード (master、専用ノードプール等) には配置されない。DaemonSet 用途では「全ノードに配置したい」 ケースが多いため必ず確認。

**能動提案**:
- master ノードにも配置するか
- Spot インスタンスノードにも配置するか
- 専用ノードプール (GPU 等) にも配置するか

**質問例**:
> 「DaemonSet なので tolerations を確認させてください:
> - master ノード (control-plane) にも配置しますか?
> - Spot インスタンスノードにも配置しますか?
> - 全ノードでログを取るのが目的なら、`operator: Exists` で全 taint に対応することを推奨します」

### 3. 外部からの受信がある場合

ユーザーが「外部からポート XX で受信」 と言ったら、`behavior-patterns/traffic-ingress.md` を読み込み、**hostPort を第一候補として提案** する (DaemonSet なので 1 ノード 1 Pod が保証され、hostPort と相性が良い)。

Service.NodePort と混同しない。

### 4. リソースサイズ

DaemonSet は **全ノード分の Pod が起動する** ため、リソース要求を低く抑える必要がある (1 ノード 1 GB のリクエスト × 100 ノード = 100 GB)。

**能動提案**: 通常の Deployment より控えめな `requests` を提案 (例: `requests.cpu: 100m, requests.memory: 128Mi`)。

### 5. updateStrategy.maxSurge

`hostPort` を使う DaemonSet では `maxSurge` を必ず `0` にする (port conflict 回避)。`hostPort` を使わない場合は通常 `0` のままで問題ない。

---

## よく該当する behavior-pattern

- `traffic-ingress.md` (受信がある場合 → hostPort 推奨)
- `application-config.md` / `config-mount.md` (rsyslog.conf 等の設定ファイル)
- `ephemeral-write.md` (readOnlyRootFilesystem 下のバッファ領域)
- `health-check.md` (probe、UDP プロトコルなら exec probe 必須)
- `graceful-shutdown.md` (バッファドレイン)
- `resource-sizing.md` (低めの requests/limits)
- `observability.md` (メトリクス公開)

---

## よくある落とし穴 (Phase 2 セルフチェック対象)

- **hostPort と Service.NodePort を混同していないか**: DaemonSet で外部受信なら hostPort が標準。Service.NodePort はクラスタの NodePort range (デフォルト 30000-32767) 制約あり、混同して指定するとデプロイ時にエラーまたはクラスタ設定変更が必要
- **PriorityClassName が空のまま**: DaemonSet 用途なら能動提案で必ず判断を促したか確認
- **tolerations が空のまま**: 全ノード配置か特定ノード配置か確認したか
- **hostNetwork: true** を安易に提案していないか: PSS Baseline/Restricted 違反。組織標準違反になる
- **`maxSurge` と `maxUnavailable` が両方 0**: k8s が拒否 (バリデーションエラー)
- **`hostPort` 使用時に `maxSurge > 0`**: ローリング更新で port conflict
- **DaemonSet で `replicaCount` を指定**: 無意味 (DaemonSet は replicaCount フィールド自体を持たない)
