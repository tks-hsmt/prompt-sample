# RBAC 最小権限ルール

本リファレンスでは RBAC リソースの最小権限原則と禁止事項に関するルールを定める。

本ドキュメントのルールは、**可能な限り `values.schema.json` で機械的に強制** し、`values.schema.json` で表現できない構造的制約はチャートテンプレートに `fail` 関数で埋め込む。

---

## ワイルドカードの禁止

`rules[].verbs`, `rules[].resources`, `rules[].apiGroups` のいずれにも **`*`(ワイルドカード)を使用してはならない**。必要な値を明示的に列挙する。

**良い例**:
```yaml
rules:
  - apiGroups: [""]
    resources: ["configmaps", "secrets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get"]
```

**悪い例**:
```yaml
rules:
  - apiGroups: ["*"]
    resources: ["*"]
    verbs: ["*"]
```
```yaml
# 部分的なワイルドカードもすべて禁止
rules:
  - apiGroups: [""]
    resources: ["*"]
    verbs: ["get", "list"]
```
```yaml
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["*"]
```

理由:
- `*` は「すべて」を意味するが、**将来 Kubernetes に新しい verb / resource / apiGroup が追加されたときも自動的にその新しい要素に対する権限が付与される**。
- `verbs: ["*"]` には `impersonate`, `escalate`, `bind`, `approve` などの危険な verb も含まれ、事実上 cluster-admin 相当の権限となる。
- `resources: ["*"]` は、後から CRD がクラスタにインストールされたとき、そのカスタムリソースに対しても自動的にフルアクセス権を持つことになる。
- 必要な値を明示列挙することで、レビュー時に権限範囲が一目で分かり、意図しない権限が紛れ込むのを防げる。

---

## resourceNames による絞り込み

`resourceNames` を指定できる verb(`get`, `update`, `patch`, `delete`)では、**可能な限り対象を絞り込むことを推奨する**。

ただし `create`, `list`, `watch`, `deletecollection` は `resourceNames` と組み合わせられない Kubernetes RBAC の仕様上の制約があるため、これらの verb については絞り込み対象外とする。

**良い例**:
```yaml
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "update"]
    resourceNames:
      - {{ include "myapp.fullname" . }}-feature-flags
      - {{ include "myapp.fullname" . }}-runtime-config
```

**改善の余地がある例**(ルール違反ではないが、絞り込みを推奨):
```yaml
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "update"]
    # resourceNames なし → namespace 内のすべての ConfigMap にアクセス可能
```

理由:
- `resourceNames` なしの Role は「その namespace 内のその種類のリソース全部」にアクセス権を与える。同じ namespace に他のアプリが動いている場合、それらのリソースにもアクセスできてしまう。
- `resourceNames` で自分が使うリソースだけに限定すれば、侵害時の横展開を防げる。
- `list` / `watch` は仕様上 `resourceNames` と組み合わせられないため必須化できないが、`get` / `update` / `patch` / `delete` では積極的に活用する。

---

## Secret へのアクセス制限

Secret リソースは **特別扱い** とする。以下のルールを **必須** とする。

- **`secrets` リソースへの `get` verb は、必ず `resourceNames` で対象を絞り込む**
- **`secrets` リソースへの `list` および `watch` verb は禁止する**

**良い例**:
```yaml
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get"]
    resourceNames:
      - {{ include "myapp.fullname" . }}-db-credentials
      - {{ include "myapp.fullname" . }}-api-keys
```

**悪い例**:
```yaml
# resourceNames なしの get
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get"]
```
```yaml
# list / watch は禁止
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["list", "watch"]
    resourceNames:
      - myapp-db-credentials    # list/watch では resourceNames が効かない
```

理由:
- Secret はクラスタ内の秘密情報の集積所である。データベースパスワード、API キー、TLS 秘密鍵、`imagePullSecrets`、そして **他の ServiceAccount のトークン** までもが格納されうる。
- Secret への広範なアクセス権は、クラスタ全体への権限昇格ルートになりうる。たとえば、`cluster-admin` 権限を持つ SA のトークンを読めれば、クラスタ全体を制御できる。
- `list` / `watch` は Kubernetes RBAC の仕様上 `resourceNames` による絞り込みが効かないため、これを許可すると namespace 内のすべての Secret が読めることになる。よって禁止する。
- `get` + `resourceNames` なら「自分が使う Secret だけ」を明示的に指定でき、影響範囲を限定できる。

---

## 危険な verb とリソースの禁止

以下の verb とサブリソースは、**RBAC 自体を悪用した権限昇格**、または **任意の Pod 制御によるクラスタ乗っ取り** に使えるため、**原則として禁止** する。

### 禁止する verb

| verb | 危険性 |
|---|---|
| `impersonate` | 他のユーザー / グループ / ServiceAccount になりすませる。cluster-admin 相当の SA になりすませば事実上任意の権限取得が可能 |
| `escalate` | 自分が持っていない権限を持つ Role を作成できる。通常 Kubernetes が行う privilege escalation 防止を回避 |
| `bind` | 自分が持っていない権限を他人に付与できる。他の SA を昇格させる経路になる |
| `approve` | CertificateSigningRequest を承認できる。任意の証明書を発行してユーザーなりすましが可能 |

### 禁止するサブリソース

| サブリソース | 危険性 |
|---|---|
| `pods/exec` | 任意の Pod で任意のコマンドを実行できる。`kube-system` 内の Pod で exec すればクラスタ全体を制御可能 |
| `pods/attach` | 実行中のコンテナにアタッチできる。`pods/exec` とほぼ同等の危険性 |
| `pods/portforward` | 任意の Pod への直接接続が可能。内部サービスへのアクセス経路となる |

### 禁止する RBAC リソースへの書き込み

以下のリソースに対する `create`, `update`, `patch`, `delete` verb は禁止する(`get`, `list`, `watch` は読み取り用途として許容):

- `roles.rbac.authorization.k8s.io`
- `clusterroles.rbac.authorization.k8s.io`
- `rolebindings.rbac.authorization.k8s.io`
- `clusterrolebindings.rbac.authorization.k8s.io`

**悪い例**(いずれも禁止):
```yaml
rules:
  - apiGroups: [""]
    resources: ["users", "serviceaccounts"]
    verbs: ["impersonate"]
```
```yaml
rules:
  - apiGroups: ["rbac.authorization.k8s.io"]
    resources: ["roles"]
    verbs: ["create", "escalate"]
```
```yaml
rules:
  - apiGroups: [""]
    resources: ["pods/exec"]
    verbs: ["create"]
```
```yaml
rules:
  - apiGroups: ["rbac.authorization.k8s.io"]
    resources: ["rolebindings"]
    verbs: ["create", "update", "patch", "delete"]
```

理由:
- `impersonate` を持つ SA は `kubectl --as=system:admin` のような操作で cluster-admin になりすませる。アプリケーションがこれを必要とする正当な理由はほぼない(認証プロキシなど極めて特殊なケースのみ)。
- `escalate` / `bind` は RBAC の privilege escalation 防止機構を回避する経路となる。攻撃者が SA を乗っ取った後、cluster-admin 相当の Role を作成して自分に bind することで cluster-admin 取得に至る。
- `pods/exec` は任意の Pod で任意のコマンド実行を可能にし、`hostNetwork: true` や `privileged: true` で動いているシステム Pod で exec すればノード自体を制御できる。
- RBAC リソース自体への書き込み権限は、他のすべての RBAC 制約をバイパスする経路となる。自分自身に任意の権限を付与して昇格できる。

これらを真に必要とするチャート(RBAC 管理ツール、cert-manager、Argo CD 等のプラットフォームコンポーネント)は、本ルール体系の対象外とする。そのようなチャートは個別の schema 例外を定義し、レビューを経て導入すること。

---

## `cluster-admin` バインディングの禁止

**チャートから `cluster-admin` ClusterRole への `RoleBinding` / `ClusterRoleBinding` を作成してはならない**。

**悪い例**:
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: {{ include "myapp.fullname" . }}-admin
subjects:
  - kind: ServiceAccount
    name: {{ include "myapp.serviceAccountName" . }}
    namespace: {{ .Release.Namespace }}
roleRef:
  kind: ClusterRole
  name: cluster-admin
  apiGroup: rbac.authorization.k8s.io
```

理由:
- `cluster-admin` は Kubernetes にビルトインされた ClusterRole で、クラスタ全体に対する完全な制御権(`verbs: ["*"]`, `resources: ["*"]`, `apiGroups: ["*"]`)を持つ。
- このバインディングが存在する状態で、その SA を使う Pod が侵害されると、攻撃者は即座にクラスタ全体の完全制御を獲得する。
- 真に cluster-admin 相当を必要とするプラットフォームコンポーネントは本ルール体系の対象外であり、個別の schema 例外を定義する。

---

## values.schema.json による機械的強制

本ルールは **可能な限り `values.schema.json` で機械的に強制する**。具体的には以下を schema で検証する。

### 強制項目

1. `rbac.create` と `serviceAccount.create` の型検証(boolean 必須)
2. `rules[].verbs`, `rules[].resources`, `rules[].apiGroups` への `*` の禁止
3. 禁止 verb のチェック(`impersonate`, `escalate`, `bind`, `approve`)
4. 禁止サブリソースのチェック(`pods/exec`, `pods/attach`, `pods/portforward`)
5. RBAC リソースへの書き込み禁止(`roles`, `clusterroles`, `rolebindings`, `clusterrolebindings` への `create`/`update`/`patch`/`delete`)
6. `secrets` への `list` / `watch` の禁止
7. `secrets` への `get` 時の `resourceNames` 必須
8. `cluster-admin` バインディングの禁止

### schema 実装イメージ
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "definitions": {
    "rbacRule": {
      "type": "object",
      "properties": {
        "apiGroups": {
          "type": "array",
          "items": {
            "type": "string",
            "not": { "const": "*" }
          }
        },
        "resources": {
          "type": "array",
          "items": {
            "type": "string",
            "not": {
              "enum": [
                "*",
                "pods/exec",
                "pods/attach",
                "pods/portforward"
              ]
            }
          }
        },
        "verbs": {
          "type": "array",
          "items": {
            "type": "string",
            "not": {
              "enum": [
                "*",
                "impersonate",
                "escalate",
                "bind",
                "approve"
              ]
            }
          }
        },
        "resourceNames": {
          "type": "array",
          "items": { "type": "string" }
        }
      },
      "required": ["apiGroups", "resources", "verbs"]
    }
  },
  "properties": {
    "rbac": {
      "type": "object",
      "properties": {
        "create": { "type": "boolean" }
      },
      "required": ["create"]
    },
    "serviceAccount": {
      "type": "object",
      "properties": {
        "create": { "type": "boolean" },
        "name": { "type": "string" },
        "annotations": { "type": "object" },
        "automountToken": { "type": "boolean" }
      },
      "required": ["create", "automountToken"]
    },
    "rules": {
      "type": "array",
      "items": { "$ref": "#/definitions/rbacRule" }
    }
  }
}
```

### schema で表現できない制約

以下はチャートテンプレート側で実装する。

- **`Secret` への `get` 時の `resourceNames` 必須**: 特定リソース(`secrets`)に特定 verb(`get`)を組み合わせたときのみ別フィールド(`resourceNames`)を必須化するのは JSON Schema の `if`/`then` 構文で表現可能だが複雑になる。テンプレート側で `fail` 関数を使って検証することも併用する。
- **`cluster-admin` への `RoleBinding` / `ClusterRoleBinding` の禁止**: テンプレートで `roleRef.name` が `cluster-admin` の場合に `fail` を呼ぶ。
```gotemplate
{{/* templates/rolebinding.yaml */}}
{{- if .Values.rbac.create }}
{{- if eq .Values.rbac.roleRef.name "cluster-admin" }}
{{- fail "cluster-admin への RoleBinding / ClusterRoleBinding は禁止されています。rbac-least-privilege.md を参照してください。" }}
{{- end }}
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
# ...
{{- end }}
```

理由:
- schema で拒否できない構造的ルール(特定の組み合わせでのみ発生する制約)は、テンプレート側の `fail` 関数で補完する。
- `fail` によるエラーは `helm template` / `helm install` / `helm lint` で検出され、CI 段階で止められる。
- schema とテンプレートの二段構えにすることで、どちらか一方をすり抜けるような記述を防ぐ。