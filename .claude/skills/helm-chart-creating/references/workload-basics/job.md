# ワークロード基礎: Job

一回限りのバッチ処理。完了するまで実行され、完了後は Pod が残る (ログ確認用)。

## 該当するアプリの典型例

- DB マイグレーション
- データ集計、バックアップ
- 一回限りのデプロイメントタスク
- ML モデル学習 (一回限り)

## Job 固有パラメータ

| パラメータ | デフォルト | 意味 |
|---|---|---|
| `restartPolicy` | `OnFailure` (本スキル既定、k8s 必須指定) | コンテナ失敗時の再起動 |
| `backoffLimit` | `6` | リトライ回数上限 |
| `activeDeadlineSeconds` | なし | 全体実行時間上限 |
| `ttlSecondsAfterFinished` | `3600` (本スキル既定) | 完了後の自動削除待機秒数 |
| `completions` | `1` | 必要成功 Pod 数 |
| `parallelism` | `1` | 並列実行最大数 |

### `restartPolicy`

| 値 | 挙動 | 使い所 |
|---|---|---|
| **`OnFailure`** | 同一 Pod 内でコンテナ再起動 | 冪等な処理 |
| `Never` | 失敗時に新規 Pod 起動 (失敗 Pod は残る) | デバッグログを残したい |

`Always` は使えない (k8s が拒否)。

### `backoffLimit`

| 値 | 挙動 |
|---|---|
| **`6`** (k8s 既定) | 最大 6 回リトライ。**指数バックオフ** (10s → 20s → 40s ...、最大 6 分間隔) |
| `0` | リトライなし、即失敗 |

### `ttlSecondsAfterFinished`

| 値 | 挙動 |
|---|---|
| なし (k8s 既定) | Job が永久に残る (手動削除が必要) |
| **`3600`** (本スキル既定) | 完了 1 時間後に自動削除 |
| `0` | 即削除 |

---

## Job での能動的提案

### 1. 処理時間の見積もり

`activeDeadlineSeconds` を能動的に提案:
> 「想定実行時間はどれくらいですか? ハングアップ対策に `activeDeadlineSeconds` で上限を設定することを推奨します」

### 2. リトライ要否

冪等な処理かを確認。冪等なら `backoffLimit` をデフォルトのまま (6)、非冪等なら `0` を提案:
> 「バッチが途中失敗した場合、自動リトライしますか? 処理が冪等 (何度実行しても同じ結果) なら 6 回リトライを推奨、非冪等ならリトライなし (`backoffLimit: 0`) を推奨します」

### 3. ログ保持期間

`ttlSecondsAfterFinished` の調整:
> 「Job 完了後、何時間ログを残しますか? (デフォルト 1 時間)」

### 4. 並列処理

通常 `completions: 1`、`parallelism: 1`。並列処理が必要な場合のみ調整:
> 「並列処理は必要ですか? 例えば 100 件のデータを 10 並列で処理する場合は `completions: 100, parallelism: 10` 等を推奨します」

---

## よく該当する behavior-pattern

- `application-config.md` / `config-mount.md`
- `resource-sizing.md` — Job は短時間なので大きめに振っても OK
- `cloud-resource-access.md` — DB マイグレーションで RDS にアクセス等

通常 **不要**: `traffic-ingress.md` (Job は外部受信しない), `health-check.md` (probe は必要ない、終了で判断), `replica-scaling.md` (HPA/PDB は無関係)

---

## よくある落とし穴 (Phase 2 セルフチェック対象)

- **`restartPolicy: Always` を指定**: k8s が拒否
- **サービスメッシュ (Istio/Linkerd) サイドカーが終了しない問題**: 旧来の挙動。Istio 1.19+ の native sidecar 機能か `holdApplicationUntilProxyStarts` 等の対策が必要
- **`backoffLimit` 設定なしで非冪等処理**: 重複実行リスク
- **`ttlSecondsAfterFinished` なし**: Job リソースが永久に残ってクラスタを汚染
- **`activeDeadlineSeconds` なしで長時間ハング可能性のある処理**: ノードリソースを占有し続ける
