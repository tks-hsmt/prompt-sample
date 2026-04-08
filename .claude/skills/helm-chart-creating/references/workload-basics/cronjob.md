# ワークロード基礎: CronJob

定期スケジュール実行するバッチ処理。指定スケジュールごとに Job を生成する。

## 該当するアプリの典型例

- 定期バックアップ
- 定期集計、レポート生成
- 定期ヘルスチェック、クリーンアップ
- 定期データ同期

## CronJob 固有パラメータ

| パラメータ | デフォルト | 意味 |
|---|---|---|
| `schedule` | (必須) | Vixie Cron 形式 (5 フィールド) |
| `timeZone` | なし (バージョン依存あり) | スケジュールのタイムゾーン |
| `concurrencyPolicy` | `Forbid` (本スキル既定、k8s は `Allow`) | 重複実行ポリシー |
| `startingDeadlineSeconds` | なし | スケジュール起動の遅延許容秒数 |
| `successfulJobsHistoryLimit` | `3` | 成功 Job 保持数 |
| `failedJobsHistoryLimit` | `1` | 失敗 Job 保持数 |
| `suspend` | `false` | 一時停止 |

### `schedule`

Vixie Cron 形式: `分 時 日 月 曜日`

| 例 | 意味 |
|---|---|
| `0 2 * * *` | 毎日 02:00 |
| `*/15 * * * *` | 15 分毎 |
| `0 0 * * 0` | 毎週日曜 00:00 |

**注意**: `schedule` フィールド内に `TZ=Asia/Tokyo` や `CRON_TZ=...` を含めることはバリデーションエラー (廃止された旧挙動)。タイムゾーンは `timeZone` フィールドを使う。

### `concurrencyPolicy`

| 値 | 挙動 | 使い所 |
|---|---|---|
| **`Forbid`** (本スキル既定) | 前回実行中なら次回スキップ | 排他必須なバッチ |
| `Allow` (k8s 既定) | 並列実行 | 短時間で独立なバッチ |
| `Replace` | 前回を中断して新規起動 | 常に最新で実行 |

---

## CronJob での能動的提案

### 1. スケジュール (必須質問)

ユーザーの言葉 (「毎日早朝」 「15 分毎」 等) から cron 形式に変換:
> 「実行スケジュールを教えてください。例: 毎日 02:00、15 分毎、毎週月曜日 09:00 等」

### 2. タイムゾーン

組織が JST 基準なら `Asia/Tokyo` を能動提案:
> 「このバッチのスケジュールは JST 基準ですか? UTC 基準ですか? `timeZone: Asia/Tokyo` を設定することを推奨します (バージョン依存あり、対象クラスタで利用可能か確認します)」

### 3. 重複実行の挙動

ユーザーに確認:
> 「前回のバッチがまだ実行中に次回のスケジュールが来た場合、どうしますか?
> - スキップして次々回まで待つ (`Forbid`、本スキル既定)
> - 並列実行する (`Allow`)
> - 前回を中断して新規実行 (`Replace`)」

### 4. 履歴保持

通常デフォルト (成功 3 / 失敗 1) で十分。デバッグ要件が強い場合のみ調整提案。

---

## よく該当する behavior-pattern

Job と同じ。`application-config.md`、`resource-sizing.md`、`cloud-resource-access.md` 等。

CronJob 自身は外部受信しないため `traffic-ingress.md` は不要。

---

## よくある落とし穴 (Phase 2 セルフチェック対象)

- **`schedule` 内に `TZ=Asia/Tokyo` を含める**: バリデーションエラー
- **`startingDeadlineSeconds` を 10 秒未満に設定**: CronJob が全くスケジュールされなくなる (公式動作)
- **`timeZone` をバージョン非対応の k8s で使用**: 設定が無視される
- **`concurrencyPolicy: Allow` で長時間バッチを多重起動**: リソース枯渇
- **Job と同様、サービスメッシュサイドカー終了問題**: native sidecar 等の対策が必要
