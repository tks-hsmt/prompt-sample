# 振る舞いパターン: データ永続化 (PVC)

PVC、StorageClass、accessModes 等、データ永続化に関わる構成。

## 該当判定

- アプリがデータを永続化する必要がある (DB、ストレージ、メッセージキュー等)
- ユーザーが「データを残す」 「再起動後もデータ保持」 等を言及

## ワークロード別の適用

| WL | 該当度 | 注意 |
|---|---|---|
| Deployment | △ | PVC 使用は可能だが、複数 Pod で共有なら ReadWriteMany が必須 |
| DaemonSet | △ | 通常は hostPath か emptyDir。PVC は限定的 |
| StatefulSet | ✅ **中心** | `volumeClaimTemplates` で Pod ごとに PVC 自動作成 |
| Job / CronJob | △ | 一時的に PVC 使用するケースあり (バックアップ等) |

---

## アクセスモード

| モード | 挙動 | 使い所 |
|---|---|---|
| **`ReadWriteOnce`** (RWO) | 1 ノードで読み書き可。同一ノード上の複数 Pod が使用可 | EBS、PD、Azure Disk 等のブロックストレージ標準 |
| `ReadOnlyMany` (ROX) | 複数ノードで読み取り専用 | 設定配布等 |
| `ReadWriteMany` (RWX) | 複数ノードで読み書き | NFS、EFS、Azure Files、CephFS 等の共有ファイルシステム |
| `ReadWriteOncePod` (RWOP) | **単一 Pod のみ** 読み書き (RWO よりさらに厳格) | 単一 Pod 占有を強制したい場合 |

> ⚠️ **`ReadWriteOncePod` はバージョン依存あり**: 古い k8s や CSI ドライバでは未対応。Phase 2 計画生成時に対象クラスタで利用可否を `web_search` で確認。

**注意**: `ReadWriteOnce` は **同一ノード上なら複数 Pod から使用可能**。「単一 Pod のみ」 ではないため誤解しない。完全な単一 Pod 制限が必要なら `ReadWriteOncePod` を使う。

---

## StorageClass

| 設定 | 挙動 |
|---|---|
| `""` (デフォルト) | クラスタの default StorageClass を使用 |
| `-` | StorageClass を使わない (静的 PV のみ) |
| 具体名 (`gp3`, `io2`, `pd-balanced`) | 指定 StorageClass を使用 |

**代表例**:
- AWS: `gp3` (汎用), `io2` (高 IOPS), `efs-sc` (RWX)
- GCP: `pd-balanced` (汎用), `pd-ssd` (高速), `filestore` (RWX)
- Azure: `managed-csi` (汎用), `azurefile-csi` (RWX)

---

## 能動的提案

### 1. データ永続化の必要性確認

ステートフルアプリ (DB、メッセージキュー等) なら必ず確認:
> 「このアプリはデータを永続化する必要がありますか? (再起動後もデータが残る必要があるか)」

### 2. データ量の見積もり

容量を能動的に確認:
> 「想定されるデータ量はどれくらいですか? 拡張可能な StorageClass (`gp3` 等) を使えば後から増やせますが、最初は保守的な値で開始することを推奨します」

### 3. 共有要件の確認 (ReadWriteOnce/Many の判断)

ユーザー言語で確認:
> 「データを複数の Pod から同時に読み書きする必要がありますか?
> - 同時アクセスなし → 通常のブロックストレージ (EBS/PD 等)
> - 複数 Pod から同時読み書き → 共有ファイルシステム (EFS/NFS 等) が必要」

### 4. PVC 削除ポリシー (StatefulSet)

データ消失リスク最小化のため `Retain` を強く推奨:
> 「StatefulSet を削除またはスケールダウンした際、PVC を残しますか?
> - **Retain (推奨)**: PVC を残す。データ保護
> - Delete: PVC も自動削除。**誤操作で全データ消失**のリスク」

> ⚠️ `persistentVolumeClaimRetentionPolicy` 機能自体がバージョン依存。Phase 2 で確認。

### 5. バックアップ戦略

> 「PVC のバックアップ戦略は決まっていますか? (Velero、CSI snapshot、アプリ層バックアップ等)」

---

## Phase 1 で確認すべき項目

| 項目 | 例 |
|---|---|
| 永続化要否 | Yes/No |
| データ量 | 10Gi、100Gi 等 |
| StorageClass | クラスタで利用可能なもの |
| アクセスモード | RWO / RWX (用途次第で Claude が判断) |
| 削除ポリシー | StatefulSet なら Retain 推奨 |
| バックアップ | 別途検討 |

---

## よくある落とし穴 (Phase 2 セルフチェック対象)

- **`persistence.enabled: false` でデータ永続化が必要なアプリ**: 再起動でデータロスト
- **`storageClass: ""` で cluster default が無効**: PVC が pending のまま
- **`accessModes: [ReadWriteMany]` 指定だが StorageClass が対応していない**: PVC pending
- **Deployment で PVC を使い、複数 Pod に ReadWriteOnce で attach**: PVC が複数ノードに attach できずスケジューリング失敗
- **`persistence.size` 縮小**: 一般に PVC は縮小不可
- **`persistentVolumeClaimRetentionPolicy.whenScaled: Delete`**: 誤スケールダウンで全データ消失
- **`ReadWriteOnce` を「単一 Pod 制限」 と誤解**: 同一ノード上なら複数 Pod が使える。完全単一が必要なら `ReadWriteOncePod`
