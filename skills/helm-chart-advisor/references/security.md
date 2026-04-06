# セキュリティ：securityContext の詳細設定

## 目次

- [runAsNonRoot: true — 非rootユーザーでの実行](#runasnonroot-true--非rootユーザーでの実行)
- [runAsUser / runAsGroup / fsGroup — UID/GID の明示指定](#runasuser--runasgroup--fsgroup--uidgid-の明示指定)
- [allowPrivilegeEscalation: false — 権限昇格の拒否](#allowprivilegeescalation-false--権限昇格の拒否)
- [readOnlyRootFilesystem: true — 読み取り専用ルートファイルシステム](#readonlyrootfilesystem-true--読み取り専用ルートファイルシステム)
- [capabilities.drop: ALL — Linux ケーパビリティの全削除](#capabilitiesdrop-all--linux-ケーパビリティの全削除)
- [seccompProfile.type: RuntimeDefault — システムコールフィルタリング](#seccompprofiletype-runtimedefault--システムコールフィルタリング)
- [Helm チャートでの設定パターン](#helm-チャートでの設定パターン)
- [NetworkPolicy の組み込み](#networkpolicy-の組み込み)
- [ServiceAccount と automountServiceAccountToken](#serviceaccount-と-automountserviceaccounttoken)

## `runAsNonRoot: true` — 非rootユーザーでの実行

**設定内容**: Pod レベルの `securityContext` に `runAsNonRoot: true` を設定する。

**目的と効果**: コンテナプロセスが root（UID 0）で実行されることを Kubernetes が拒否する。万が一コンテナが侵害された場合でも、root 権限による被害を防止できる。

## `runAsUser` / `runAsGroup` / `fsGroup` — UID/GID の明示指定

**設定内容**: `runAsUser: 1000`、`runAsGroup: 1000`、`fsGroup: 1000` のように非root のUID/GIDを明示的に指定する。

**目的と効果**: `runAsNonRoot: true` だけではコンテナイメージの Dockerfile に USER が定義されていない場合にエラーとなるため、明示的に UID を指定することで確実に非root実行を保証する。`fsGroup` はマウントされたボリュームのファイル所有グループを設定する。

## `allowPrivilegeEscalation: false` — 権限昇格の拒否

**設定内容**: コンテナレベルの `securityContext` に `allowPrivilegeEscalation: false` を設定する。

**目的と効果**: `no_new_privs` フラグがコンテナプロセスに設定され、setuid/setgid バイナリを使った権限昇格が不可能になる。未設定の場合はデフォルトで `true` となる。

## `readOnlyRootFilesystem: true` — 読み取り専用ルートファイルシステム

**設定内容**: コンテナレベルの `securityContext` に `readOnlyRootFilesystem: true` を設定する。書き込みが必要なディレクトリ（`/tmp`、`/var/cache` 等）は `emptyDir` ボリュームで個別にマウントする。

**目的と効果**: 攻撃者がコンテナ内にマルウェアを配置したり、アプリケーションのバイナリを改ざんすることを防止する。

```yaml
containers:
  - name: app
    securityContext:
      readOnlyRootFilesystem: true
    volumeMounts:
      - name: tmp
        mountPath: /tmp
      - name: cache
        mountPath: /var/cache/nginx
volumes:
  - name: tmp
    emptyDir: {}
  - name: cache
    emptyDir: {}
```

## `capabilities.drop: ["ALL"]` — Linux ケーパビリティの全削除

**設定内容**: コンテナレベルで `capabilities.drop: ["ALL"]` を設定し、必要なケーパビリティだけを `add` で追加する。

**目的と効果**: デフォルトでコンテナに付与される Linux ケーパビリティをすべて除去し、攻撃面を最小化する。1024番以下のポートをバインドする必要がある場合のみ `NET_BIND_SERVICE` を追加する。

## `seccompProfile.type: RuntimeDefault` — システムコールフィルタリング

**設定内容**: Pod レベルの `securityContext` に `seccompProfile.type: RuntimeDefault` を設定する。

**目的と効果**: コンテナランタイムのデフォルト seccomp プロファイルを適用し、危険なシステムコール（`ptrace`, `mount` 等）をブロックする。

## Helm チャートでの設定パターン

上記すべてを values.yaml でオーバーライド可能にする。

```yaml
# values.yaml
podSecurityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
  seccompProfile:
    type: RuntimeDefault

containerSecurityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  runAsUser: 1000
  capabilities:
    drop:
      - ALL
```

テンプレートでの展開:
```yaml
spec:
  template:
    spec:
      securityContext:
        {{- toYaml .Values.podSecurityContext | nindent 8 }}
      containers:
        - name: {{ .Chart.Name }}
          securityContext:
            {{- toYaml .Values.containerSecurityContext | nindent 12 }}
```

---

# NetworkPolicy の組み込み

## デフォルト deny + 明示的 allow パターン

**設定内容**: チャート内に NetworkPolicy テンプレートを含め、`values.yaml` の `networkPolicy.enabled` で有効/無効を制御する。デフォルトで全トラフィックを拒否し、必要な通信のみを許可するホワイトリスト方式を採用する。

```yaml
# values.yaml
networkPolicy:
  enabled: true
  allowSameNamespace: true
```

**目的と効果**: Podへの不正アクセスをネットワークレベルで遮断する。攻撃者がコンテナを侵害しても横方向の移動（lateral movement）を制限できる。

---

# ServiceAccount と automountServiceAccountToken

## 専用 ServiceAccount の作成

**設定内容**: `serviceAccount.create: true` でチャート専用の ServiceAccount を作成し、`default` ServiceAccount の使用を避ける。

**目的と効果**: `default` ServiceAccount は namespace 内の全 Pod で共有されるため、RBAC で権限を付与すると意図しない Pod にも権限が波及する。専用 ServiceAccount により最小権限原則を実現する。

## `automountServiceAccountToken: false`

**設定内容**: Kubernetes API にアクセスする必要がない Pod では `automountServiceAccountToken: false` を設定する。

**目的と効果**: デフォルトでは ServiceAccount のトークンが全 Pod に自動マウントされる。API アクセスが不要な Pod ではトークンのマウントを無効化することで、コンテナ侵害時のAPI経由の攻撃面を排除する。

```yaml
# values.yaml
serviceAccount:
  create: true
  name: ""
  automountToken: false
```

