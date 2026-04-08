# Pod セキュリティルール

本リファレンスではPodおよびPodTemplateのセキュリティ設定に関するルールについて記述します。

---

## 非 root 実行

Pod およびコンテナは **必ず非 root ユーザーで実行する**。以下をすべて必須とする。

| フィールド | 必須値 | 設定先 |
|---|---|---|
| `runAsNonRoot` | `true` | Pod レベルとコンテナレベルの両方 |
| `runAsUser` | **0 以外の整数**(既定値: `1000`) | Pod レベル(コンテナで上書き可) |
| `runAsGroup` | **0 以外の整数**(既定値: `1000`) | Pod レベル(コンテナで上書き可) |
| `fsGroup` | **0 以外の整数**(既定値: `1000`) | Pod レベルのみ |

**良い例**:
```yaml
# values.yaml
podSecurityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000

containerSecurityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
```

**悪い例**:
```yaml
podSecurityContext:
  runAsUser: 0                  # root
  runAsGroup: 0                 # GID 0 もセキュリティ監査で禁止

containerSecurityContext:
  runAsNonRoot: false           # 禁止
```

理由:
- root で動作するコンテナは、コンテナブレイクアウト発生時にノードを完全制御される可能性がある。
- `runAsGroup: 0`(GID 0)はroot グループ所有のファイルへのアクセス権を持つため、本ルールでは非ゼロを強制する。
- `runAsNonRoot: true` は「コンテナイメージに `USER` 指定が root の場合に起動を拒否する」セーフティネットとしても機能する。これによりイメージビルド側のミスも検出できる。

---

## 権限昇格の禁止

コンテナは **権限昇格を禁止する**。`allowPrivilegeEscalation: false` をコンテナレベルで必須とする。また、特権コンテナ(`privileged: true`)は禁止する。

**良い例**:
```yaml
containerSecurityContext:
  allowPrivilegeEscalation: false
  privileged: false
```

**悪い例**:
```yaml
containerSecurityContext:
  allowPrivilegeEscalation: true   # 禁止
  # または privileged: true も禁止
```

理由:
- `allowPrivilegeEscalation: false` は Linux の `no_new_privs` フラグを有効化し、`setuid` バイナリや file capabilities による権限昇格を封じる。
- `privileged: true` はホスト名前空間へのフルアクセスを許し、コンテナの分離を無効化する。これが必要なワークロード(CNI プラグイン等)は Helm チャートで書くべきではなく、プラットフォーム側の別管理とする。

---

## ルートファイルシステムの読み取り専用化

コンテナのルートファイルシステムは **読み取り専用とする**。`readOnlyRootFilesystem: true` をコンテナレベルで必須とする。書き込みが必要なディレクトリは `emptyDir` を明示的にマウントする。

標準テンプレートでは **`/tmp` の `emptyDir` マウントを既定で提供** する。アプリ固有の書き込み先がある場合は values の `extraVolumes` / `extraVolumeMounts` で追加する。

**良い例**:
```yaml
# values.yaml
containerSecurityContext:
  readOnlyRootFilesystem: true

# /tmp は標準テンプレートで自動的に emptyDir がマウントされる
# アプリ固有の書き込み先がある場合のみ追記
extraVolumes:
  - name: cache
    emptyDir:
      sizeLimit: 100Mi
extraVolumeMounts:
  - name: cache
    mountPath: /var/cache/nginx
```
```gotemplate
# templates/deployment.yaml(標準テンプレート)
spec:
  template:
    spec:
      containers:
        - name: {{ .Chart.Name }}
          securityContext:
            readOnlyRootFilesystem: true
          volumeMounts:
            - name: tmp
              mountPath: /tmp
            {{- with .Values.extraVolumeMounts }}
            {{- toYaml . | nindent 12 }}
            {{- end }}
      volumes:
        - name: tmp
          emptyDir: {}
        {{- with .Values.extraVolumes }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
```

**悪い例**:
```yaml
containerSecurityContext:
  readOnlyRootFilesystem: false    # 禁止
```

理由:
- 読み取り専用ルートにより、コンテナ侵害後に攻撃者が任意のバイナリを書き込んで実行する「書いて実行」パターンを封じられる。
- アプリが書き込みを必要とするディレクトリは限定的であることが多く(`/tmp`, キャッシュ、ログ等)、明示的に `emptyDir` をマウントすれば実用上問題ない。
- よく書き込みが発生する場所は次の通り。アプリ種別ごとに必要分を `extraVolumes` / `extraVolumeMounts` で追加すること。

| アプリ種別 | 主な書き込み先 |
|---|---|
| Nginx | `/var/cache/nginx`, `/var/run` |
| Apache | `/var/log/httpd`, `/var/run/httpd` |
| Java | `/tmp`(JIT キャッシュ、`hsperfdata_<user>` 等) |
| Python | `/tmp`, `~/.cache/pip`(実行時 pip 呼び出し時) |
| PostgreSQL | `/var/run/postgresql` |

---

## Linux ケーパビリティ

Linux ケーパビリティは **すべて drop し、必要な最小限のみを追加する**。

- `capabilities.drop: ["ALL"]` を必須とする
- `capabilities.add` は **`NET_BIND_SERVICE` のみ許可** する(1024 番以下のポートを非 root でバインドするため)
- それ以外のケーパビリティ追加は `values.schema.json` で拒否する

**良い例**:
```yaml
# values.yaml
containerSecurityContext:
  capabilities:
    drop:
      - ALL
    add:
      - NET_BIND_SERVICE   # 80/443 等の特権ポートバインドが必要な場合のみ
```

**悪い例**:
```yaml
containerSecurityContext:
  capabilities:
    drop:
      - ALL
    add:
      - SYS_ADMIN          # 禁止
      - NET_ADMIN          # 禁止
      - SYS_PTRACE         # 禁止
```

理由:
- Linux ケーパビリティは root 権限を細分化したもので、一つ一つが強力な特権を持つ。`SYS_ADMIN` は事実上 root 相当である。
- `NET_BIND_SERVICE` だけは非 root で 80/443 ポートをバインドするために正当な理由があるため、例外として許可する。
- `SYS_ADMIN` 等が必要な正当なワークロード(監視エージェント、CNI 等)は Helm チャートで書くべきではなく、別管理とする。

---

## Seccomp プロファイル

コンテナランタイムの seccomp プロファイル(`RuntimeDefault`)を **必須で適用する**。これにより危険なシステムコール(`reboot`, `kexec_load` 等)を制限する。

**良い例**:
```yaml
# values.yaml
podSecurityContext:
  seccompProfile:
    type: RuntimeDefault
```

**悪い例**:
```yaml
podSecurityContext:
  seccompProfile:
    type: Unconfined         # 禁止
```
```yaml
# seccompProfile の指定自体がない = Unconfined 相当で禁止
podSecurityContext: {}
```

理由:
- `RuntimeDefault` は containerd / CRI-O が提供する安全な seccomp プロファイルで、約 60 種類の危険なシステムコールをブロックする。アプリケーションが通常動作で使うシステムコールは制限されない。
- `Unconfined` はすべてのシステムコールを許可し、Restricted プロファイル違反となる。
- `Localhost` プロファイルは運用上の柔軟性が必要なケース(例: 特殊な syscall が必要なアプリ)で使うが、デフォルトとしては禁止する。

---

## ServiceAccount トークンの自動マウント

ServiceAccount トークンは **既定でマウントしない**。`automountServiceAccountToken: false` を既定値とし、Kubernetes API へアクセスする必要のある Pod のみ values で `true` に上書きする。

**良い例**(一般的なアプリ、K8s API アクセスなし):
```yaml
# values.yaml
serviceAccount:
  automountToken: false
```

**良い例**(K8s API アクセスが必要なオペレータ等):
```yaml
serviceAccount:
  automountToken: true
rbac:
  create: true               # 必要な権限を Role で付与
```

**悪い例**:
```yaml
serviceAccount:
  automountToken: true       # K8s API を使わないのに自動マウント有効
```

理由:
- SA トークンはコンテナ内に JWT ファイルとしてマウントされ、Kubernetes API に対する認証情報となる。Pod が侵害された場合、攻撃者はこのトークンで API サーバを操作できる。
- ほとんどの業務アプリは K8s API にアクセスしないため、トークンをマウントする理由がない。攻撃面を縮小するため既定で無効化する。

---

## ホスト名前空間の使用禁止

Pod は **ホスト名前空間を使用しない**。`hostNetwork`, `hostPID`, `hostIPC` はすべて `false` とする。

ただし、**DaemonSet チャートテンプレートに限り**、`values.schema.json` で `hostNetwork: true` への上書きを許可する。Deployment / StatefulSet / Job / CronJob チャートテンプレートでは schema で `false` 固定とする。

**良い例**(通常のワークロード):
```yaml
# values.yaml (Deployment / StatefulSet / Job / CronJob)
hostNetwork: false
hostPID: false
hostIPC: false
```

**良い例**(DaemonSet 系のノードエージェント):
```yaml
# values.yaml (DaemonSet チャート)
hostNetwork: true              # ログコレクタ、監視エージェント等で許容
hostPID: false                 # 原則 false、必要時のみ true
```

**悪い例**:
```yaml
# values.yaml (Deployment チャート)
hostNetwork: true              # schema 違反。Deployment では許可されない
```

理由:
- ホスト名前空間の共有はコンテナ分離を大幅に弱め、Pod からホストのネットワーク・プロセス・IPC へアクセスできるようにする。
- ただし、DaemonSet で動くノードエージェント(Fluent Bit, Node Exporter, Falco, Datadog Agent, CNI プラグイン等)は **プラットフォーム機能として正当な理由で `hostNetwork` を必要とする**。代表的なケース:
  - ログコレクタがノード IP で外部送信先に直接接続する
  - Prometheus の Node Exporter がノードメトリクスを公開する
  - CNI プラグインがノード自身のネットワークスタックを構成する
  - NodeLocal DNSCache が `169.254.20.10` にバインドする
- そのため DaemonSet チャートテンプレートに限り例外を許容するが、`hostPID` / `hostIPC` は DaemonSet でも原則 `false` とし、必要な場合のみ values で上書きする運用とする。

---

## Pod Security Standards Restricted プロファイルとの対応関係

本ルールは Pod Security Standards の Restricted プロファイルをベースに、さらに当社環境向けの追加要件(`runAsGroup` 非ゼロ、`NET_BIND_SERVICE` 以外のケーパビリティ禁止)を加えたものである。**クラスタ側でも namespace ラベル `pod-security.kubernetes.io/enforce: restricted` を付与することで二重に強制する** ことを推奨する。
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

これにより、`values.schema.json` でのチャートビルド時チェックに加えて、Kubernetes API サーバ側でも Pod 作成時にバリデーションが走り、ルール違反の Pod がクラスタへ到達することを二重に防げる。
