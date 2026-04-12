# 一般的な慣例

本リファレンスでは一般的なルールについて記述します。

---

## YAML のフォーマット

YAML ファイルは **スペース 2 つでインデント** する。タブは使用しない。

**良い例**:
```yaml
spec:
  replicas: 3
  selector:
    matchLabels:
      app: myapp
```

**悪い例**:
```yaml
spec:
    replicas: 3
    selector:
        matchLabels:
            app: myapp
```

理由:
- 4スペース、タブ、不揃いなインデントは Helm コミュニティの慣例から外れ、レビュー時の差分やテンプレート出力との混在で読みづらくなる。

---

## "Helm" と "Chart" という単語の使い方

ドキュメント・README・コミットメッセージなどの文章中での表記ルール:

- **Helm**: プロジェクト全体を指す固有名詞。先頭は大文字。
- **`helm`**: クライアント側のコマンドを指すときは小文字でコード表記。
- **chart**: 固有名詞ではないため大文字にしない。
- **`Chart.yaml`**: ファイル名はケースセンシティブなので、必ずこの表記を守る。
- 迷ったら **Helm**(大文字 H)を使う。

**良い例**:
```markdown
Helm はパッケージマネージャです。`helm install` でチャートをインストールできます。
チャートのメタデータは `Chart.yaml` に記述します。
```

**悪い例**:
```markdown
helm はパッケージマネージャです。`Helm install` でChartをインストールできます。
チャートのメタデータは `chart.yaml` に記述します。
```

理由:
- `helm`(プロジェクト名としての小文字)、`Helm install`(コマンドなのに大文字)、`Chart`(固有名詞でないのに大文字)、`chart.yaml`(ファイル名のケース違反)は、いずれも公式ドキュメントの規約に反する。

---

## チャートテンプレートと namespace

チャートテンプレートの `metadata` セクションに **`namespace` を直接定義しない**。Helm はテンプレートをそのままレンダリングして Kubernetes クライアントに送るだけなので、適用先 namespace は `helm install --namespace` などのフラグで指定する。

**良い例**:
```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
```
```bash
helm install myapp ./myapp --namespace production
```

**悪い例**:
```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
  namespace: production
```

理由:
- テンプレートに namespace をハードコードすると、同じチャートを複数 namespace に再利用できない。
- `helm install --namespace` や GitOps ツール(flux, spinnaker など)から渡される namespace と食い違い、デプロイ先が混乱する。
- namespace の決定権はチャート側ではなく **デプロイを実行するクライアント側** に置くのが Helm の設計思想。

---

## リソースの `metadata.name` 命名規約

すべてのリソースの `metadata.name` は `{{ include "<chart>.fullname" . }}` をベースとし、リソース種別に応じたサフィックスを付与する。

### サフィックス規約

| リソース種別 | サフィックス | 例 |
|---|---|---|
| ワークロード（Deployment, StatefulSet, DaemonSet, Job, CronJob） | なし | `{{ include "myapp.fullname" . }}` |
| Service | `-svc` | `{{ include "myapp.fullname" . }}-svc` |
| ServiceAccount | `-sa` | `{{ include "myapp.fullname" . }}-sa` |
| ConfigMap | `-config` | `{{ include "myapp.fullname" . }}-config` |
| Secret | `-secret` | `{{ include "myapp.fullname" . }}-secret` |
| Role | `-role` | `{{ include "myapp.fullname" . }}-role` |
| RoleBinding | `-rolebinding` | `{{ include "myapp.fullname" . }}-rolebinding` |
| Ingress | `-ingress` | `{{ include "myapp.fullname" . }}-ingress` |
| HorizontalPodAutoscaler | `-hpa` | `{{ include "myapp.fullname" . }}-hpa` |
| PodDisruptionBudget | `-pdb` | `{{ include "myapp.fullname" . }}-pdb` |
| NetworkPolicy | `-netpol` | `{{ include "myapp.fullname" . }}-netpol` |
| PersistentVolumeClaim | `-pvc` | `{{ include "myapp.fullname" . }}-pvc` |

同種のリソースが複数ある場合は、サフィックスの後にさらに識別名を追加する（例: `{{ include "myapp.fullname" . }}-config-nginx`）。

### 既存リソース名との不一致

レビューにおいて、既存リソースの `metadata.name` が上記サフィックス規約と異なる場合は違反として報告する。ただし修正モードでは、ユーザーが明示的に依頼しない限りリソース名を変更しない。リソース名の変更は既存の Service 参照や RBAC バインディングを破壊する可能性があるため、影響範囲をユーザーに提示し判断を委ねる。
