# 振る舞いパターン: グレースフルシャットダウン

Pod 削除時にコンテナがバッファのドレイン、接続のクローズ等を完了するための猶予時間と挙動制御。

## 該当判定

- アプリがバッファ/キューを持つ (rsyslog, fluentd, Kafka 等)
- 長時間接続を扱う (WebSocket, gRPC streaming, 長いポーリング HTTP)
- DB へのトランザクションを途中で持つ
- 終了時にクリーンアップ処理が必要

## ワークロード別の適用

| WL | 該当度 |
|---|---|
| Deployment | ✅ よくある |
| DaemonSet | ✅ バッファ系で重要 |
| StatefulSet | ✅ DB 系で必須 |
| Job / CronJob | ❌ 通常完了で終わる |

---

## 関連パラメータ

| パラメータ | デフォルト | 意味 |
|---|---|---|
| `terminationGracePeriodSeconds` | `30` | SIGTERM → SIGKILL までの秒数 |
| `lifecycle.preStop.exec.command` | なし | SIGTERM の前に実行するコマンド |
| `lifecycle.preStop.httpGet` | なし | SIGTERM の前に呼ぶ HTTP エンドポイント |

---

## Pod 削除のシーケンス

1. Pod 削除リクエスト (kubectl delete, helm upgrade 等)
2. **Service endpoints から除外** (新規トラフィック停止)
3. **`preStop` hook 実行** (指定されていれば)
4. **コンテナに SIGTERM 送信**
5. **`terminationGracePeriodSeconds` 待機**
6. 期限切れなら **SIGKILL 強制終了**

**重要**: `preStop` の実行時間 + アプリのドレイン時間 < `terminationGracePeriodSeconds` でなければならない。

---

## 能動的提案

### 1. バッファ系アプリ (rsyslog, fluentd 等)

```
このアプリはバッファを持つので、グレースフルシャットダウンを設定します:

- terminationGracePeriodSeconds: 60 (デフォルト 30 秒では足りない可能性)
- preStop: バッファをフラッシュするコマンドを実行
  例 (rsyslog): SIGTERM 前に kill -HUP で再オープン後、少し待つ
  例 (fluentd): /bin/sh で flush コマンド実行

バッファサイズと転送先の遅延次第で調整します。想定バッファ滞留時間はどれくらいですか?
```

### 2. 長時間接続 (WebSocket, gRPC streaming)

```
このアプリは長時間接続を扱うので、以下を設定します:

- terminationGracePeriodSeconds: 想定最大接続時間に応じて (例: 300 秒)
- preStop: sleep 5-10 秒で readiness probe を fail させて新規接続を止める
  (Service endpoint からの除外には数秒のラグがあるため)
- アプリ側で SIGTERM 受信時に既存接続を gracefully close する実装

readiness probe の `failureThreshold * periodSeconds` も短くしておくと早く endpoint から外れます。
```

### 3. DB 系 (StatefulSet)

```
DB の安全停止は重要です:

- terminationGracePeriodSeconds: 120-300 秒 (チェックポイント、トランザクションフラッシュ)
- preStop: DB の安全停止コマンド (例: PostgreSQL なら pg_ctl stop -m fast)
- アプリのデフォルト挙動を確認: SIGTERM 受信で安全停止する DB か?

公式ドキュメントで停止挙動を確認します。
```

### 4. 通常の Web/API

デフォルト 30 秒で十分なケースが多い。ただし以下は確認:
- 接続プールのドレイン (DB 接続、外部 API 接続)
- インフライトリクエストの完了

---

## preStop の典型パターン

### sleep で readiness fail を待つ

```yaml
lifecycle:
  preStop:
    exec:
      command: ["/bin/sh", "-c", "sleep 10"]
```

readiness probe が失敗するまでの時間を稼ぎ、新規トラフィックを止めてから SIGTERM を送る。10 秒程度が一般的。

### アプリ固有のドレインコマンド

```yaml
lifecycle:
  preStop:
    httpGet:
      path: /admin/drain
      port: 8080
```

アプリが drain エンドポイントを持つ場合。

---

## Phase 1 で確認すべき項目

| 項目 | 例 |
|---|---|
| バッファ/接続の有無 | rsyslog のキュー、WebSocket 等 |
| 想定ドレイン時間 | バッファサイズ、接続数 |
| アプリの SIGTERM 時挙動 | Graceful 対応か、強制終了か |
| preStop の必要性 | sleep / drain endpoint / アプリ固有コマンド |
| terminationGracePeriodSeconds | preStop + ドレイン時間以上 |

---

## よくある落とし穴 (Phase 2 セルフチェック対象)

- **`terminationGracePeriodSeconds < preStop 実行時間 + ドレイン時間`**: SIGKILL で強制終了されデータ消失
- **アプリが SIGTERM を無視する設計**: ドレインコマンドが必要
- **PID 1 問題**: シェルスクリプトで起動したアプリは SIGTERM を子プロセスに転送しない (`exec` で起動するか、`tini` 等の init を使う)
- **probe の failureThreshold * periodSeconds が terminationGracePeriodSeconds より長い**: probe 失敗を待つうちに SIGKILL される
- **preStop で無限ループ**: terminationGracePeriodSeconds で強制終了されるが、設計ミス
- **DB の StatefulSet で graceful shutdown 未設定**: トランザクション破損リスク
