# 振る舞いパターン: リソース要求 (CPU/メモリ requests/limits)

`resources.requests` と `resources.limits` の設計、QoS クラスの選択。

## 該当判定

全ワークロードで該当 (Job/CronJob 含む)。本番運用では必須。

## ワークロード別の特性

| WL | 特性 |
|---|---|
| Deployment | 通常負荷ベースで設定。HPA との連動 |
| DaemonSet | **全ノード分起動するため低めに抑える** (例: 1 ノード × 100 = 100 倍消費) |
| StatefulSet | 安定動作のため余裕を持たせる |
| Job | 短時間で完了するため大きめでも OK |
| CronJob | Job と同じ |

---

## 関連パラメータ

| パラメータ | 説明 |
|---|---|
| `resources.requests.cpu` | スケジューリング時の最低保証 (例: `100m`) |
| `resources.requests.memory` | スケジューリング時の最低保証 (例: `128Mi`) |
| `resources.limits.cpu` | 上限。超過時はスロットリング |
| `resources.limits.memory` | 上限。超過時は OOM kill |

## 単位

| CPU | 意味 |
|---|---|
| `1` | 1 コア |
| `500m` | 0.5 コア |
| `100m` | 0.1 コア |

| メモリ | 意味 |
|---|---|
| `1Gi` | 1 * 2^30 bytes (推奨 2 進単位) |
| `512Mi` | 512 * 2^20 bytes |

---

## QoS クラス

| QoS | 条件 | eviction 順位 |
|---|---|---|
| **Guaranteed** | CPU/Memory ともに `requests == limits` かつ > 0 | 最後 (最も安定) |
| **Burstable** | Guaranteed 条件未満で何らか requests/limits 設定済み | 中間 |
| **BestEffort** | requests も limits も設定なし | 最初 (最も不安定) |

**注**: limit のみ指定すると k8s が自動的に `requests = limits` をセットする。

---

## 能動的提案

### 1. アプリ種別から初期値を提案

ユーザーが明確な要求量を持っていない場合、Claude が能動的に提案:

| アプリ種別 | 初期提案 |
|---|---|
| Web/API (Deployment) | requests: cpu 100m, memory 128Mi / limits: cpu 500m, memory 256Mi |
| バッチワーカー (Deployment) | requests: cpu 200m, memory 256Mi / limits: cpu 1, memory 512Mi |
| ログ収集 (DaemonSet) | requests: cpu 100m, memory 128Mi / limits: cpu 500m, memory 256Mi |
| DB (StatefulSet) | アプリの推奨値ベース。最低 cpu 500m, memory 1Gi |
| Job/CronJob | 処理規模ベース |

> 「実際の負荷から最適値を見つけるため、まずは保守的な値で始めて、本番環境でメトリクスを観察しながら調整することを推奨します」

### 2. JVM 系アプリの場合

```
JVM 系アプリは heap 以外にもメモリを使うので、限界注意:

- requests.memory: heap size + メタスペース + ネイティブメモリ (heap × 1.5 程度が目安)
- limits.memory: requests の 1.2-1.5 倍程度
- JVM の Xmx (最大 heap) は limits.memory より小さく (例: limits 1Gi なら Xmx 768m)
- JDK 10+ なら -XX:MaxRAMPercentage=75 等で自動調整可
```

### 3. HPA を使う場合

```
HPA を有効にする場合、resources.requests.cpu の設定が必須です。
HPA は requests.cpu に対する利用率でスケーリング判断するためです。
```

→ `replica-scaling.md` と整合確認

### 4. DaemonSet の場合

```
DaemonSet は全ノードで起動するため、リソース要求を低めに抑えます。
ノード数 × Pod のリソース消費 = クラスタ全体の消費 になります。
```

### 5. Guaranteed QoS の提案

```
クリティカルなワークロード (金融、決済、重要 DB 等) では、
requests == limits にして Guaranteed QoS にすることを推奨します。
ノードリソース枯渇時に最後まで evict されません。
```

---

## Phase 1 で確認すべき項目

| 項目 | 例 |
|---|---|
| アプリの典型的負荷 | リクエスト/秒、データ量等 |
| メモリ使用パターン | 起動時、定常時、ピーク時 |
| HPA の有無 | requests.cpu の必須性 |
| 環境別差分 | dev は小さく、prod は大きく |
| クリティカル度 | Guaranteed QoS の要否 |

---

## よくある落とし穴 (Phase 2 セルフチェック対象)

- **`autoscaling.enabled: true` で `resources.requests.cpu` 未設定**: HPA が動作しない
- **`limits.memory` 未設定**: ノードのメモリ枯渇時に evict 対象になりやすい
- **`limits.cpu` を厳しく設定**: スロットリングでレイテンシ悪化
- **JVM の Xmx > limits.memory**: 起動後すぐ OOM kill
- **DaemonSet で大きすぎる requests**: ノード配置失敗 (スケジューリング不可)
- **`limits` のみ設定で requests 未設定**: 暗黙的に requests = limits となり想定外
- **Burstable で `limits >> requests`**: ノード上で他 Pod とリソース競合
