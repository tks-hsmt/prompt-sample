# 振る舞いパターン: 監視 (メトリクス・ログ)

Prometheus メトリクス公開、ログ出力方針、サービスメッシュ連携。

## 該当判定

- アプリが Prometheus メトリクスを公開する
- アプリのログを集約基盤に送る
- サービスメッシュ (Istio, Linkerd) を使用

## ワークロード別の適用

| WL | 該当度 |
|---|---|
| Deployment | ✅ |
| DaemonSet | ✅ (rsyslog 自身のメトリクスも) |
| StatefulSet | ✅ |
| Job / CronJob | △ Prometheus Pushgateway 経由が一般的 |

---

## メトリクス公開: 2 つの方式

### 方式 A: Prometheus Operator (PodMonitor / ServiceMonitor)

クラスタが Prometheus Operator を使っている場合の標準。CRD で検出を制御。

**注意**: 本スキルは現状 PodMonitor/ServiceMonitor を生成しない (templates に未含)。必要なら別途作成。

### 方式 B: アノテーションベース

Prometheus Operator なしの環境、または scrape config で `kubernetes_sd` を使う環境。

```yaml
podAnnotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "9090"
  prometheus.io/path: "/metrics"
```

**注意**: Prometheus Operator 環境ではこのアノテーションは効果なし。

---

## 能動的提案

### 1. Prometheus 検出方式の確認

メトリクス公開ありなら能動的に確認:
> 「メトリクスを公開するとのことなので、Prometheus 検出方式を確認させてください:
> - クラスタは Prometheus Operator を使っていますか? (PodMonitor/ServiceMonitor で検出)
> - それとも標準アノテーション (`prometheus.io/scrape`) で検出していますか?
> 
> Prometheus Operator なら本スキルでは PodMonitor を生成しないため、別途作成をご検討ください」

### 2. メトリクスポートと標準パス

| アプリ種類 | 慣習ポート | 慣習パス |
|---|---|---|
| Spring Boot Actuator | 8080 | /actuator/prometheus |
| Go (`promhttp.Handler`) | 9090 or 2112 | /metrics |
| Node.js (`prom-client`) | 9090 | /metrics |
| nginx-prometheus-exporter | 9113 | /metrics |
| rsyslog (impstats) | 8514 (任意) | カスタム |

### 3. ログ出力方針 (組織標準と整合)

`organization-standards.md` の通り、**stdout/stderr が標準**。能動的に提案:

> 「アプリログは stdout/stderr に出力する標準を採用しています。クラスタの集約ログ基盤 (fluentd/fluent-bit DaemonSet 等) が自動で収集する想定です。
> 
> もしファイルログが必須なら、`emptyDir` に書き出してサイドカーで stdout 転送するパターンを検討します」

### 4. サービスメッシュ注入

```yaml
podAnnotations:
  sidecar.istio.io/inject: "true"      # Istio
  linkerd.io/inject: enabled            # Linkerd
```

**Job/CronJob での重大な注意**: サイドカーが終了しないと Job 完了と見なされない (旧来挙動)。Istio 1.19+ の native sidecar 機能、または `holdApplicationUntilProxyStarts` 等の対策が必要。能動的に確認:

> 「Job/CronJob でサービスメッシュサイドカーを使う場合、サイドカー終了問題に対応する必要があります。クラスタの Istio バージョンは何ですか?」

---

## Phase 1 で確認すべき項目

| 項目 | 例 |
|---|---|
| メトリクス公開 | あり/なし |
| メトリクスポート/パス | 8080/actuator/prometheus 等 |
| Prometheus 検出方式 | PodMonitor/ServiceMonitor / アノテーション |
| ログ出力 | stdout/stderr (推奨) / ファイル |
| サービスメッシュ | Istio / Linkerd / なし |
| メッシュサイドカー Job 問題 | Job/CronJob で関係 |

---

## よくある落とし穴 (Phase 2 セルフチェック対象)

- **Prometheus Operator 環境でアノテーション方式を使う**: 検出されない
- **メトリクスポートを `containers[].ports` に含めない**: NetworkPolicy で blocked される可能性
- **ファイルログを `readOnlyRootFilesystem: true` 下で書こうとする**: 書き込み失敗 (`ephemeral-write.md` 参照)
- **Job/CronJob でサイドカー終了問題未対応**: Job が永久に Running 状態
- **メトリクスエンドポイントを認証なしで本番公開**: 情報漏洩リスク (NetworkPolicy で制限を)
