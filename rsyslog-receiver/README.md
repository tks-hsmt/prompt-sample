# rsyslog-receiver

A Helm chart for rsyslog syslog receiver with RFC5424 validation and fluentd forwarding

![Version: 0.1.0](https://img.shields.io/badge/Version-0.1.0-informational?style=flat-square)
![AppVersion: 8.2404.0](https://img.shields.io/badge/AppVersion-8.2404.0-informational?style=flat-square)

## 概要

本チャートは通信装置からのシスログを受信する rsyslog を Deployment としてデプロイする。
受信メッセージの RFC5424 形式チェックを行い、準拠メッセージのみを後続の fluentd へ転送し、非準拠メッセージは破棄する。

### 前提条件

- Kubernetes 1.28 以降
- 転送先 fluentd が稼働していること (`forwarder.target` / `forwarder.port` で指定)
- 通信装置から Service の公開ポート (デフォルト: 514/UDP) へ到達可能であること

### 環境別デプロイ

各環境への適用は、対応する `values-{env}.yaml` を `-f` で指定して `helm upgrade --install` を実行する。

```bash
helm upgrade --install rsyslog-receiver ./rsyslog-receiver -n logging -f rsyslog-receiver/values-prod.yaml
```

## 設定値

> helm-docs で自動生成される。`values.yaml` の `# --` コメントを参照。

## メンテナ

| Name | Email | Url |
| ---- | ----- | --- |
| takeshi.hashimoto |  |  |
