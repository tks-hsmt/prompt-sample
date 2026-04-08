# 振る舞いパターン: レプリカ管理 (replicaCount, HPA, PDB)

Deployment と StatefulSet で複数レプリカを運用する場合のスケーリング設計。

## 該当判定

- Deployment または StatefulSet
- 複数レプリカで HA を確保したい
- 負荷変動に応じてオートスケールしたい
- ノードドレイン時の HA 保証が必要

## ワークロード別の適用

| WL | 該当度 |
|---|---|
| Deployment | ✅ 中心 (HPA/PDB と組合せ) |
| StatefulSet | ✅ 適用可 (ただし HPA は通常使わない、PDB は重要) |
| DaemonSet | ❌ レプリカ数はノード数で決定 |
| Job | △ `parallelism` で別管理 |
| CronJob | ❌ |

---

## 関連パラメータ

### replicaCount

| 値 | 挙動 | 使い所 |
|---|---|---|
| `1` | 単一 Pod | dev、検証 |
| `2` | 最小 HA | 軽量本番 |
| **`3+`** | 本番標準 | HA + AZ 分散可 |

**Quorum 系** (etcd, Zookeeper, Kafka 等) は奇数 (3, 5, 7) が必須。

### HPA (`autoscaling`)

| パラメータ | デフォルト | 説明 |
|---|---|---|
| `autoscaling.enabled` | `false` (本スキル既定) | HPA リソース作成有無 |
| `autoscaling.minReplicas` | `1` | スケール下限 |
| `autoscaling.maxReplicas` | `10` (本スキル既定) | スケール上限 |
| `autoscaling.targetCPUUtilizationPercentage` | `70` | CPU 使用率の目標 |

**HPA アルゴリズム** (公式): `desired = ceil(current * (currentMetric / desiredMetric))`

**前提**:
- クラスタに metrics-server がインストール済み
- `resources.requests.cpu` が設定済み (HPA は requests に対する比率で計算)

**`minReplicas: 0`** (scale-to-zero) は alpha 機能で本スキルでは原則非推奨。

### PDB (`podDisruptionBudget`)

| パラメータ | デフォルト | 説明 |
|---|---|---|
| `podDisruptionBudget.enabled` | `false` (本スキル既定) | PDB リソース作成有無 |
| `podDisruptionBudget.minAvailable` | `1` | 常時稼働すべき最小 Pod 数 (整数 or %) |

**役割**: ノードドレイン等の **自発的中断** 時に最低稼働数を保証。**非自発的中断** (ノード障害) は対象外。

---

## 能動的提案

### 1. 本番想定なら replicaCount >= 3 を推奨

```
本番運用ですか? それとも開発/検証ですか?
- 本番なら replicaCount: 3 以上を推奨します (AZ 分散可、PDB と組み合わせ)
- dev/stg は環境別 values で 1-2 にできます
```

### 2. HPA の能動提案

```
このアプリは負荷変動がありますか?
- 変動あり (Web/API、トラフィックスパイクあり) → HPA を推奨
  - resources.requests.cpu の設定必須 (HPA の前提)
  - minReplicas: 2 以上を推奨 (常時 HA)
  - maxReplicas はクラスタリソース上限を考慮
- 変動なし (バックエンドワーカー、ステートフル) → replicaCount 固定
```

### 3. PDB の能動提案

```
本番運用でノードドレイン時の HA を保証しますか?
- replicaCount >= 2 なら PDB 有効化を推奨
- minAvailable は replicaCount の半分以上 (例: replicaCount: 3 → minAvailable: 2)
- HPA と組み合わせる場合は % 指定 (例: minAvailable: 50%)
```

**重要な注意**:
- `replicaCount: 1` で `minAvailable: 1` → **永久にノードドレイン不可** (cluster-autoscaler が動かなくなる)
- `minAvailable >= replicaCount` も同じ問題

### 4. AZ 分散の提案

```
マルチ AZ クラスタなら topologySpreadConstraints で AZ 分散を推奨します:
- maxSkew: 1
- topologyKey: topology.kubernetes.io/zone
- whenUnsatisfiable: DoNotSchedule (厳格) または ScheduleAnyway (ベストエフォート)
```

---

## Phase 1 で確認すべき項目

| 項目 | 例 |
|---|---|
| 環境 | dev / stg / prod |
| 本番のレプリカ数 | 3, 5 等 |
| 負荷変動の有無 | HPA 要否 |
| ピーク負荷の見積もり | maxReplicas 決定 |
| HA 要件 | PDB 要否 |
| AZ 分散要件 | topologySpreadConstraints |
| Quorum 系か | レプリカ数を奇数にする |

---

## よくある落とし穴 (Phase 2 セルフチェック対象)

- **`replicaCount: 1` で `podDisruptionBudget.minAvailable: 1`**: 永久にノードドレイン不可、cluster-autoscaler 停止
- **`minAvailable >= replicaCount`**: 同上
- **`autoscaling.enabled: true` で `resources.requests.cpu` 未設定**: HPA が動作しない
- **HPA で `minReplicas: 1`**: スケールイン時に単一構成、HA なし
- **StatefulSet で HPA**: 順序保持と整合しない、原則使わない
- **Quorum 系を偶数レプリカで運用**: split-brain リスク
- **HPA `maxReplicas` がクラスタリソース上限を超える**: スケールアウト失敗
- **本番で PDB なし**: ノードドレインで全 Pod 同時 evict 可能性
