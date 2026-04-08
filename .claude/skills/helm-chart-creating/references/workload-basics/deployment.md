# ワークロード基礎: Deployment

ステートレスなアプリ (Web/API、ワーカー等) の標準ワークロード。

## 該当するアプリの典型例

- Web/API サーバ (nginx, Spring Boot, Node.js, FastAPI 等)
- バックエンドワーカー (キュー消費型)
- ステートレスなマイクロサービス

## Deployment 固有パラメータ

| パラメータ | デフォルト | 意味 |
|---|---|---|
| `strategy.type` | `RollingUpdate` | 更新戦略 |
| `strategy.rollingUpdate.maxSurge` | `25%` | 一時超過可能 Pod 数 |
| `strategy.rollingUpdate.maxUnavailable` | `25%` | 不在許容 Pod 数 |
| `revisionHistoryLimit` | `10` | 保持する旧 ReplicaSet 数 |

### `strategy.type`

| 値 | 挙動 | 使い所 |
|---|---|---|
| **`RollingUpdate`** (k8s 既定) | 段階的に新旧入れ替え。ダウンタイムなし | 通常の Web/API |
| `Recreate` | 全停止 → 全起動。ダウンタイム発生 | 新旧バージョン混在不可 (DB スキーマ不整合等) |

### `strategy.rollingUpdate.maxSurge` / `maxUnavailable`

| パラメータ | 意味 |
|---|---|
| `maxSurge` | 更新中、`replicaCount` を超えて作成可能な Pod 数 (整数 or %) |
| `maxUnavailable` | 更新中、不在を許容する Pod 数 (整数 or %) |

**両方 0 不可** (k8s が拒否)。

---

## Deployment での能動的提案

Deployment ワークロード確定時、Claude は以下を自動的に検討し、該当する behavior-pattern を読み込んで能動提案する:

### 必ず確認すべきこと

1. **`replicaCount`**: 何台で運用するか (本番なら 3 以上が一般的)
2. **`resources.requests` / `limits`**: CPU/メモリの要求量 (リソース見積)
3. **liveness / readiness probe**: ヘルスチェック方式
4. **外部公開有無**: Service / Ingress / NetworkPolicy の構成
5. **設定ファイル/環境変数**: ConfigMap / Secret の必要性

### よく該当する behavior-pattern

- `replica-scaling.md` (replicaCount, HPA, PDB)
- `resource-sizing.md` (requests/limits)
- `health-check.md` (probe)
- `traffic-ingress.md` (Service/Ingress)
- `application-config.md` / `config-mount.md` (設定)
- `graceful-shutdown.md` (長時間接続を持つ場合)
- `observability.md` (Prometheus メトリクス)

### よくある落とし穴 (Phase 2 セルフチェック対象)

- `replicaCount: 1` で PDB `minAvailable: 1` → 永久にノードドレイン不可
- `autoscaling.enabled: true` で `resources.requests.cpu` 未設定 → HPA が動作しない
- `strategy.type: Recreate` で本番運用 → ダウンタイム発生 (意図的か確認)
- `maxSurge: 0` かつ `maxUnavailable: 0` → k8s が拒否 (バリデーションエラー)
