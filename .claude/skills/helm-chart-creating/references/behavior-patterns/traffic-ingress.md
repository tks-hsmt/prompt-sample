# 振る舞いパターン: 外部からのトラフィック受信

アプリが外部からトラフィック (HTTP/HTTPS/TCP/UDP/gRPC) を受信する場合の構成パターン。

## 該当判定

ユーザーリクエストに以下が含まれる場合に該当:
- 「外部から」「公開する」「受信する」「クライアントがアクセス」 等
- 特定のポート番号への着信
- インターネット / 社内ネットワーク / 同一クラスタからのアクセス要件

## ワークロード別の適用

| WL | 該当度 | 主な選択肢 |
|---|---|---|
| Deployment | ✅ 中心 | Service + Ingress / LoadBalancer |
| DaemonSet | ✅ 中心 | **hostPort 推奨** (1 ノード 1 Pod のため) |
| StatefulSet | △ 補助 | Headless Service + 個別 Service |
| Job | ❌ 通常不要 | - |
| CronJob | ❌ 通常不要 | - |

---

## 公開方式の選択肢と使い分け

| 方式 | 使い所 | 注意 |
|---|---|---|
| **`hostPort`** (Pod 仕様の containerPort.hostPort) | DaemonSet の UDP 受信、特定ポートを固定したい、NodePort range 外を使いたい | 1 ノード 1 Pod 前提 (DaemonSet と相性良)。Service 不要。Pod IP = ノード IP |
| **`Service` type `ClusterIP`** | クラスタ内通信 | デフォルト。外部公開不可 |
| **`Service` type `NodePort`** | クラスタ外から各ノードの一律ポートで受信 | デフォルト範囲 30000-32767。範囲外指定はクラスタの `--service-node-port-range` 変更が必要 |
| **`Service` type `LoadBalancer`** | クラウド LB を作成 | コスト発生。クラウド固有アノテーションで制御 (AWS NLB/ALB 等) |
| **`Ingress`** | HTTP/HTTPS の複数ホスト/パスを 1 つの LB で集約 | TLS 終端、cert-manager 等と組み合わせ |

---

## 能動的提案 (重要)

### 1. ユーザーが「ノード IP + ポートで受信」 と言った場合

DaemonSet なら **hostPort を第一候補で提案** する:

> 「DaemonSet で全ノードの特定ポートで受信するなら `hostPort` の使用を推奨します。
> - メリット: NodePort range の制約を受けない、Service 不要でシンプル
> - 注意: 1 ノードで該当 Pod が 1 つ前提なので DaemonSet と相性が良い
>
> Service.NodePort という別の選択肢もありますが、デフォルト range が 30000-32767 で、それ以外を使うにはクラスタ設定変更が必要です」

**hostPort と Service.NodePort を混同しない**:
- `hostPort`: Pod 仕様のフィールド (`spec.containers[].ports[].hostPort`)。Service 不要
- `Service.NodePort`: Service の `spec.type: NodePort` で生成される。`spec.ports[].nodePort`

### 2. ユーザーが「外部公開 Web/API」 と言った場合

Deployment なら **Ingress を第一候補で提案** する:

> 「外部公開する Web/API なら Ingress を推奨します。複数のアプリを 1 つの LB (ALB/NLB) で集約でき、TLS 終端も一元管理できます。
> - クラスタの Ingress Controller は何をお使いですか? (nginx-ingress、ALB Ingress Controller、Traefik 等)
> - 公開ドメイン名は決まっていますか?
> - TLS 証明書は cert-manager で自動発行しますか? それとも既存証明書を使いますか?」

`LoadBalancer` 単体は 1 アプリ 1 LB でコスト高なので、明確な要件 (gRPC 専用 NLB 等) がない限り Ingress 経由を推奨。

### 3. ユーザーが受信プロトコルを明示していない場合

必ず確認:
> 「受信プロトコルは何ですか? (HTTP / HTTPS / TCP / UDP / gRPC)」

UDP の場合は `health-check.md` の能動提案 (HTTP probe 不可、exec probe 必須) を併せて実行。

### 4. ポート番号の確認

- **特権ポート (1024 未満)** を使う場合: `containerSecurityContext.capabilities.add: [NET_BIND_SERVICE]` が必要 (PSS Restricted で許可された唯一の追加 capability)
- **任意ポート**: アプリの設定で変更可能か確認

---

## Phase 1 で確認すべき項目

| 項目 | 例 |
|---|---|
| 受信プロトコル | HTTP / HTTPS / TCP / UDP / gRPC |
| 受信ポート (コンテナ側) | 80, 514, 8080 等 |
| 受信ポート (ホスト/外部側) | hostPort 20514, NodePort, Ingress URL 等 |
| 受信元 | インターネット / 社内 / 同一クラスタ |
| 公開方式 | hostPort / Service / Ingress / LoadBalancer のどれか (Claude が推奨を提示してから確認) |
| ドメイン名 (Ingress の場合) | app.example.com 等 |
| TLS 証明書 (Ingress の場合) | cert-manager か手動か |
| NetworkPolicy 必要性 | 受信元を制限したいか |

---

## よくある落とし穴 (Phase 2 セルフチェック対象)

- **`hostPort` と `Service.NodePort` の混同**: 「ノード IP + ポート 20514 で受信」 という要件に対して、Service.NodePort で 20514 を指定してしまう (デフォルト range 外で動作しない)
- **特権ポート (< 1024) を使うのに `NET_BIND_SERVICE` capability を追加し忘れ**: コンテナ起動失敗
- **DaemonSet で `hostPort` を使うのに `updateStrategy.maxSurge > 0`**: ローリング更新で port conflict
- **Service `targetPort` を番号指定で書き、Pod 側のポート変更時に追従できない**: targetPort は名前付き (`http` 等) を推奨
- **Ingress `tls` の `secretName` で参照する Secret が cert-manager 未連携**: 証明書がない
- **`LoadBalancer` 単体を複数アプリで使用 → コスト爆発**: Ingress で集約検討
- **NetworkPolicy `policyTypes` の空配列の解釈ミス**: 空 `ingress: []` は「全 Ingress 拒否」 を意味 (全許可ではない)
