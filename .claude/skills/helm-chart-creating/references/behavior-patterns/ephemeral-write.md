# 振る舞いパターン: 一時書き込み領域

`readOnlyRootFilesystem: true` (組織標準) の下で、アプリが `/tmp`、`/var/run`、`/var/spool` 等に書き込む必要がある場合の領域確保。

## 該当判定

- アプリが任意のファイルを書き込む必要がある (`/tmp`、ログファイル、PID ファイル、ソケットファイル、バッファファイル等)
- アプリ起動時に「Read-only file system」 エラーが出る (Phase 4 検証時)
- 対象ソフトの仕様で書き込みが必要な箇所が判明している (rsyslog の `/var/spool/rsyslog`、nginx の `/var/run/nginx.pid` 等)

## ワークロード別の適用

全ワークロードに該当 (組織標準で `readOnlyRootFilesystem: true` が強制されているため)

---

## 解決方法: emptyDir マウント

書き込みが必要な箇所に `emptyDir` ボリュームをマウントする。

```yaml
extraVolumes:
  - name: tmp
    emptyDir: {}
  - name: var-run
    emptyDir: {}
  - name: var-spool-rsyslog
    emptyDir: {}

extraVolumeMounts:
  - name: tmp
    mountPath: /tmp
  - name: var-run
    mountPath: /var/run
  - name: var-spool-rsyslog
    mountPath: /var/spool/rsyslog
```

---

## emptyDir のオプション

### 1. メモリベース (`medium: Memory`)

```yaml
extraVolumes:
  - name: tmp
    emptyDir:
      medium: Memory
      sizeLimit: 64Mi
```

| オプション | 挙動 |
|---|---|
| なし (デフォルト) | ノードのディスクを使用 |
| `medium: Memory` | tmpfs (RAM) を使用。**Pod の memory limit を消費** |
| `sizeLimit` | 上限サイズ。超えると Pod が evict される |

**使い所**: 高速 I/O が必要、機密データを残さない (再起動でクリア)、SSD 摩耗を避けたい。

### 2. ディスクベース (デフォルト)

ノードのディスクを使用。`sizeLimit` を指定するとそのサイズ以上で evict。

---

## 能動的提案

### 1. 対象ソフトが書き込む場所を能動的に列挙

ユーザーリクエストから対象ソフト (rsyslog, nginx, fluentd 等) を特定したら、Claude は **そのソフトが書き込む必要のある場所を能動的に列挙** する。記憶ベースで不確実な場合は公式ドキュメントを `web_fetch`。

例 (rsyslog):
> 「rsyslog は以下に書き込みます。`readOnlyRootFilesystem: true` の下では emptyDir マウントが必要です:
> - `/var/spool/rsyslog` (キューバッファ)
> - `/var/run` (PID ファイル `rsyslogd.pid`)
> - `/tmp` (一時ファイル)
>
> これらに emptyDir を割り当てます。バッファサイズが大きい場合は `sizeLimit` の指定を推奨します」

例 (nginx):
> 「nginx は以下に書き込みます:
> - `/var/run` (PID ファイル)
> - `/var/cache/nginx` (キャッシュ)
> - `/tmp` (一時ファイル)
>
> nginx 公式の non-root イメージ (`nginxinc/nginx-unprivileged`) を使うことも推奨します」

### 2. サイズ見積もりの確認

バッファ系 (rsyslog のキュー等) は容量を確認:
> 「rsyslog のキューはどれくらいのサイズを想定しますか? 受信レートと転送先の可用性次第ですが、64Mi-1Gi 程度が一般的です」

### 3. 永続化が必要な場合

emptyDir は Pod 再作成で消える。永続化が必要なら `data-persistence.md` (PVC) に切り替え:
> 「このバッファは Pod 再作成時に消えても問題ないですか? 障害時のログ消失を避けたいなら PVC を推奨します」

---

## Phase 1 で確認すべき項目

| 項目 | 例 |
|---|---|
| 対象ソフトが書き込む場所 | Claude が能動列挙、ユーザーが追加情報を提供 |
| 各場所のサイズ見積もり | バッファ系は重要 |
| medium (Memory or Disk) | 高速性 vs メモリ消費 |
| 永続化要否 | 必要なら PVC に切り替え |

---

## よくある落とし穴 (Phase 2 セルフチェック対象)

- **`readOnlyRootFilesystem: true` 下で書き込み領域 (emptyDir) を割り当てていない**: アプリ起動失敗
- **対象ソフトが書き込む場所を見落としている**: 起動後に書き込みエラー
- **`medium: Memory` で `sizeLimit` 未指定**: メモリ枯渇リスク
- **大容量バッファに `emptyDir` を使用 (永続化が必要なケース)**: 再作成でデータ消失
- **`/var/log` に emptyDir マウント (ログを stdout 出力すべき箇所)**: 組織標準違反 (ロギングは stdout/stderr)
