# ワークロード基礎: StatefulSet

順序、安定したネットワーク ID、永続ストレージが必要なワークロード。

## 該当するアプリの典型例

- データベース (PostgreSQL, MySQL, MongoDB, Cassandra 等)
- メッセージキュー (Kafka, RabbitMQ, NATS 等)
- 分散ストレージ (Elasticsearch, etcd, Zookeeper, Redis Cluster 等)
- 安定 ID が必要な分散アプリ

## StatefulSet 固有パラメータ

| パラメータ | デフォルト | 意味 |
|---|---|---|
| `podManagementPolicy` | `OrderedReady` | Pod 起動順序 |
| `updateStrategy.type` | `RollingUpdate` | 更新戦略 |
| `updateStrategy.rollingUpdate.partition` | `0` | canary 更新の境界 |
| `persistence.enabled` | `false` | PVC 作成有無 |
| `persistence.size` | (必須) | PVC 容量 |
| `persistence.storageClass` | `""` (cluster default) | StorageClass |
| `persistence.accessModes` | `[ReadWriteOnce]` | アクセスモード |
| `persistentVolumeClaimRetentionPolicy.whenDeleted` | `Retain` (バージョン依存あり) | StatefulSet 削除時の PVC 扱い |
| `persistentVolumeClaimRetentionPolicy.whenScaled` | `Retain` (バージョン依存あり) | スケールダウン時の PVC 扱い |

### `podManagementPolicy`

| 値 | 挙動 | 使い所 |
|---|---|---|
| **`OrderedReady`** (k8s 既定) | `pod-0` → `pod-1` → ... 順次起動 | 起動順序依存のあるステートフル (DB レプリカ、Quorum 系) |
| `Parallel` | 全 Pod 並列起動 | 起動順序依存なし |

**注**: 作成後の変更不可。

---

## StatefulSet での能動的提案

### 1. データ永続化の確認 (必須)

`persistence.enabled` と `persistence.size` を能動的に確認:
> 「StatefulSet なのでデータ永続化が必要だと思います。データ量はどれくらいを想定していますか? 拡張可能な StorageClass (gp3 等) を使うことを推奨します」

→ `behavior-patterns/data-persistence.md` を読み込む

### 2. PVC 削除ポリシー

データ消失リスク最小化のため `Retain` を強く推奨。Phase 1 で能動的に説明:
> 「StatefulSet を削除またはスケールダウンした際、PVC を残しますか? データ保護のため `Retain` を推奨します」

### 3. レプリカ数

Quorum 系 (etcd, Zookeeper, Kafka 等) は奇数 (3, 5, 7) を推奨。
通常の DB プライマリ-レプリカ構成は 1 (プライマリのみ) または 3 (プライマリ + リードレプリカ x2)。

### 4. ヘッドレス Service

StatefulSet は安定 DNS 名のためヘッドレス Service が必要。**自動で生成する**。ユーザーには「Pod 間で `<pod-name>.<service-name>` で通信できます」 と説明。

---

## よく該当する behavior-pattern

- `data-persistence.md` (PVC、StorageClass) — 必須
- `replica-scaling.md` (replicaCount, PDB) — HPA は通常使わない
- `resource-sizing.md`
- `health-check.md`
- `graceful-shutdown.md` — DB 系では特に重要
- `application-config.md` / `config-mount.md`

---

## よくある落とし穴 (Phase 2 セルフチェック対象)

- **`persistence.enabled: false` でデータ永続化が必要なアプリ**: データロスト
- **`storageClass` が指定なしで cluster default が無効**: PVC が pending のまま
- **`accessModes: [ReadWriteMany]` を指定しているが StorageClass が対応していない**: PVC pending
- **HPA を使おうとしている**: StatefulSet では原則使わない (順序保持と整合しない)
- **`persistence.size` を後で縮小しようとする**: PVC は通常縮小不可
- **`persistentVolumeClaimRetentionPolicy.whenScaled: Delete`**: スケールダウン誤操作で全データ消失
