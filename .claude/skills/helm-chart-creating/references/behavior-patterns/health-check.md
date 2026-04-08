# 振る舞いパターン: ヘルスチェック (probe)

Liveness / Readiness / Startup probe の構成。

## 該当判定

ほぼ全てのワークロードに該当 (Job/CronJob を除く)。

## ワークロード別の適用

| WL | 該当度 | 主な probe |
|---|---|---|
| Deployment | ✅ 必須 | liveness + readiness |
| DaemonSet | ✅ 必須 | liveness + readiness |
| StatefulSet | ✅ 必須 | liveness + readiness |
| Job / CronJob | ❌ 通常不要 | 完了で判断 |

---

## 3 つの Probe の役割

| Probe | 目的 | 失敗時 |
|---|---|---|
| **Liveness** | コンテナが生きているか | 再起動 |
| **Readiness** | リクエストを受け付け可能か | Service endpoint から除外 (再起動なし) |
| **Startup** | 起動処理完了したか | 完了するまで他 probe 無効化 |

## Probe の種類

| 種類 | 使い所 |
|---|---|
| `httpGet` | HTTP/HTTPS ベースの Web/API |
| `tcpSocket` | TCP ベースの DB、メッセージキュー、シンプル TCP サーバ |
| `exec` | 複雑な健全性チェック、UDP アプリ、PID チェック |
| `grpc` | gRPC サーバ (バージョン依存あり) |

> ⚠️ **`grpc` probe はバージョン依存**: 古い k8s では未サポート。Phase 2 で確認。利用不可の場合は `exec` で `grpc_health_probe` バイナリを実行する代替手段。

---

## タイミングパラメータ (k8s デフォルト)

| パラメータ | デフォルト | 説明 |
|---|---|---|
| `initialDelaySeconds` | `0` | 起動後最初の probe までの待機 |
| `periodSeconds` | `10` | probe 間隔 |
| `timeoutSeconds` | `1` | probe タイムアウト |
| `successThreshold` | `1` | 失敗→成功復帰に必要な連続成功数 (Liveness/Startup は 1 固定) |
| `failureThreshold` | `3` | 連続失敗で失敗判定 |

---

## 能動的提案

### 1. プロトコルから probe 種類を判断

ユーザーが受信プロトコルを言ったら自動判断:

| プロトコル | Claude の能動提案 |
|---|---|
| HTTP/HTTPS | `httpGet` を提案 (パスとポートを確認) |
| TCP | `tcpSocket` を提案 (ポートを確認) |
| **UDP** | **`exec` probe を提案** (HTTP probe 不可)。PID チェックや CLI でのテストコマンドを提案 |
| gRPC | `grpc` を提案 (バージョン対応確認)、不可なら `exec` で `grpc_health_probe` |

### 2. UDP アプリの場合 (重要)

```
このアプリは UDP 受信なので HTTP probe が使えません。以下を提案します:

- liveness probe: PID チェック (例: rsyslog なら `kill -0 $(cat /var/run/rsyslogd.pid)`)
  → プロセスが死んでいたら再起動

- readiness probe: 同じく PID チェック
  → ただし UDP は接続概念がないので、Service 経由でも probe は意味が薄い
    Service 自体を作らず hostPort で受ける構成なら readiness probe は省略でも OK

この方針でよろしいですか?
```

### 3. 起動が遅いアプリの場合

JVM、Spring Boot、ML モデルロード等で起動に 30 秒以上かかる場合:

```
このアプリは起動に時間がかかるとのことなので、startupProbe を追加することを推奨します:

- startupProbe: アプリ起動完了を確認するまで liveness/readiness を無効化
- failureThreshold: <想定起動時間 / periodSeconds + 余裕>

例: 想定起動時間 60 秒なら failureThreshold: 12 (12 * 10 = 120 秒許容)
```

### 4. terminationGracePeriodSeconds との整合

長い probe failureThreshold + 短い terminationGracePeriodSeconds は矛盾。`graceful-shutdown.md` と整合確認。

---

## Phase 1 で確認すべき項目

| 項目 | 例 |
|---|---|
| 受信プロトコル | HTTP/HTTPS/TCP/UDP/gRPC (`traffic-ingress.md` と共有) |
| ヘルスチェック方法 | アプリが提供するエンドポイント (例: `/healthz`)、PID チェック等 |
| 起動時間の想定 | startupProbe 要否 |
| timing 調整 | 一時的負荷でフラップしない閾値 |

---

## よくある落とし穴 (Phase 2 セルフチェック対象)

- **UDP アプリに `httpGet` probe を設定**: 動作しない (HTTP は TCP ベース)
- **`tcpSocket` probe を UDP ポートに設定**: TCP 接続なので UDP の状態は分からない
- **起動が遅いアプリで startupProbe なし、liveness `initialDelaySeconds` も短い**: 起動中に再起動ループ
- **`failureThreshold * periodSeconds` が短すぎる**: 一時的スパイクで再起動
- **`successThreshold > 1` を Liveness/Startup に指定**: k8s が拒否 (1 固定)
- **`gRPC` probe をバージョン非対応 k8s で使用**: 動作しない、`exec + grpc_health_probe` に切り替え必要
- **readiness probe failureThreshold が大きすぎる**: 異常な Pod がトラフィックを受け続ける
