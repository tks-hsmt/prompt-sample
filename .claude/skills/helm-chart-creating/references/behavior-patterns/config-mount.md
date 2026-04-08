# 振る舞いパターン: ConfigMap / Secret マウント

設定値や設定ファイルを ConfigMap / Secret としてコンテナに渡すパターン。

## 該当判定

- ConfigMap または Secret をコンテナにマウント、または環境変数として注入する必要がある
- `application-config.md` で生成した設定ファイルをコンテナに渡す

## ワークロード別の適用

全ワークロードに該当 (Deployment, DaemonSet, StatefulSet, Job, CronJob)

---

## ConfigMap vs Secret の判断

| 種別 | 使い所 |
|---|---|
| **ConfigMap** | 設定ファイル、環境変数、非機密情報 |
| **Secret** | パスワード、API キー、TLS 証明書、トークン、機密データ |

**判断**: ユーザーに「機密情報 (パスワード、API キー等) は含まれますか?」 と聞いて Claude が判断する。k8s 用語を直接聞かない (`hearing-principles.md`)。

---

## マウント方法の選択肢

### 1. ファイルとしてマウント (ディレクトリ全体)

```yaml
extraVolumes:
  - name: config
    configMap:
      name: app-config
extraVolumeMounts:
  - name: config
    mountPath: /etc/app
    readOnly: true
```

ConfigMap の全キーがファイルとして `/etc/app/<key>` にマウントされる。

**ConfigMap 更新時**: 数秒〜数十秒で自動反映 (kubelet が同期)。アプリが設定を再読み込みする必要あり。

### 2. ファイルとしてマウント (subPath で単一ファイル)

```yaml
extraVolumeMounts:
  - name: config
    mountPath: /etc/rsyslog.conf
    subPath: rsyslog.conf
    readOnly: true
```

ConfigMap の特定キーだけを既存ディレクトリ内のファイルとしてマウント。他のファイルは隠さない。

**注意**: **subPath マウントは ConfigMap 更新時に自動反映されない** (公式仕様)。動的更新が必要なら subPath を使わずディレクトリ全体マウントを推奨。

### 3. 環境変数として注入

```yaml
extraEnv:
  - name: DB_HOST
    valueFrom:
      configMapKeyRef:
        name: app-config
        key: db.host
  - name: DB_PASSWORD
    valueFrom:
      secretKeyRef:
        name: app-secrets
        key: db-password
```

または `envFrom` で全キーを一括注入:

```yaml
extraEnvFrom:
  - configMapRef:
      name: app-config
  - secretRef:
      name: app-secrets
```

**注意**: 環境変数は **Pod 起動時に固定** される。ConfigMap/Secret を更新しても Pod 再起動するまで反映されない。

---

## immutable オプション (バージョン依存あり)

> ⚠️ **`immutable: true` はバージョン依存**: 古い k8s では未サポート。Phase 2 計画生成時に対象クラスタで利用可能か `web_search` で公式確認。

```yaml
apiVersion: v1
kind: ConfigMap
immutable: true
data:
  ...
```

| 値 | 挙動 |
|---|---|
| なし (デフォルト) | 通常の更新可能 ConfigMap |
| `true` | 作成後変更不可。変更するには削除して再作成。kube-apiserver の watch 負荷削減 + 誤操作防止 |

**能動提案**: 更新頻度が低く、誤操作を防ぎたい本番設定では `immutable: true` を提案。

---

## 能動的提案

### 1. 設定ファイルをマウントする場合

`application-config.md` で意図ベース生成 (方式 B) を選んだ場合、Claude は以下を能動提案:

> 「rsyslog.conf を ConfigMap として作成し、`/etc/rsyslog.conf` に subPath マウントします。
> - subPath マウントなので、ConfigMap 更新時に自動反映されません (動的更新が必要なら通知してください)
> - 本番運用では `immutable: true` を推奨します (バージョン対応確認後)」

### 2. 機密情報がある場合

> 「DB パスワードや API キーがあるとのことなので、Secret を作成して環境変数として注入します。Secret の中身は手動で `kubectl apply` するか、SealedSecrets / External Secrets Operator 等で管理することを推奨します」

### 3. ConfigMap/Secret の作成方法

| 方法 | 特徴 |
|---|---|
| Helm chart 内に作成 | Chart と一緒にデプロイ。シンプル |
| 外部管理 (kubectl apply, terraform 等) | Chart とは別ライフサイクル。Secret 管理に向く |
| SealedSecrets / External Secrets Operator | GitOps と相性 |

ユーザーに方針を確認:
> 「ConfigMap/Secret の作成方法は? (Helm chart 内 / 外部管理)」

---

## Phase 1 で確認すべき項目

| 項目 | 例 |
|---|---|
| 設定値の中身 | `application-config.md` で擦り合わせ済み |
| 機密情報の有無 | パスワード等 |
| マウントパス | `/etc/app/config.yaml` 等 |
| マウント方法 | ディレクトリ全体 / subPath / 環境変数 |
| 動的更新の必要性 | アプリが設定再読み込みするか |
| ConfigMap/Secret の作成方法 | chart 内 / 外部管理 |
| immutable の使用 | 本番では推奨 |

---

## よくある落とし穴 (Phase 2 セルフチェック対象)

- **subPath マウントで動的更新を期待**: 反映されない (公式仕様)
- **環境変数注入で動的更新を期待**: Pod 再起動が必要
- **Secret を ConfigMap で扱う / ConfigMap を Secret で扱う**: 機密情報の判断ミス
- **`immutable: true` をバージョン非対応の k8s で使用**: 設定が無視される
- **Secret を Helm chart の values にハードコード**: Git 管理対象になり機密漏洩。外部管理または External Secrets Operator 推奨
- **ConfigMap/Secret 名が Pod の参照と一致しない**: マウント失敗
