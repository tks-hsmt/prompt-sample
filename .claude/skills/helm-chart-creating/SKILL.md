---
name: helm-chart-creating
description: Kubernetesワークロード（Deployment, DaemonSet, StatefulSet, Job, CronJob）向けの本番品質Helmチャートを組織標準とPod Security Standards Restrictedに準拠して新規作成する。複数ユーザー間で出力フォーマットを統一するため、ヒアリング→計画提示→作成→検証の固定ワークフローを実行する。ユーザーがアプリケーションエンジニアレベルのインフラ知識を持つ前提で、k8s固有の技術用語を直接ユーザーに問わず、アプリケーション特性から必要な設定を推論する。ユーザーが「Helmチャートを作成」「helm chart 作成」「新しいアプリのKubernetesデプロイ構成」等の依頼をした場合に使用する。
---

# helm-chart-creating

組織標準に沿った Helm チャートを複数ユーザー間で統一された出力で生成する。本 SKILL.md とリファレンスの指示から逸脱しない。

## トリガー条件

- 「Helmチャートを作成」「helm chart 作成」 等の明示的依頼
- 「新しいアプリを Kubernetes にデプロイ」 等、k8s リソース新規作成依頼

既存チャートの修正・レビューには **使用しない**。

## 想定ユーザー

アプリケーションエンジニア。k8s の基本概念は理解しているが、Helm chart のベストプラクティスには精通していない。

## 設計原則

1. **テンプレートを起点とする**: `templates/<workload>/values.yaml` には組織標準 (PSS Restricted 等) と一般的な雛形が既に組み込まれている。組織標準は固定 (`organization-standards.md`)、それ以外のパラメータは **アプリ特性に応じてテンプレートデフォルトを上書きする** ことが前提。「テンプレートデフォルトのまま放置」 は能動性の欠如と見なす
2. **k8s 技術用語を直接聞かない**: アプリ特性から必要な k8s リソースを Claude が判断する
3. **ワークロードは推論禁止**: 明示されていなければ必ず質問
4. **能動的提案が原則**: ユーザーリクエストから該当する behavior-pattern を抽出し、ベストプラクティスに沿った構成を **Claude が能動的に提案する**。受動的に「未設定」 のまま残さない
5. **計画書は確定済み内容のみ**: Phase 1 ヒアリングで全項目を擦り合わせ、Phase 2 計画書には決定済み事項のみ載せる。後出し禁止
6. **公式情報源で確認**: 設定ファイル中身や挙動の不確実な点は記憶ベースで書かず、`web_fetch` で公式ドキュメント確認
7. **バージョン依存情報は本スキルに書かない**: バージョン依存パラメータは Phase 1 で対象クラスタバージョンを確認し、Phase 2 で必要なら実行時 `web_search`
8. **組織標準違反禁止**: `references/organization-standards.md` のルールを破らない

## ファイル構成

```
references/
├── organization-standards.md       # 固定ルール (全チャート適用、ヒアリング対象外)
├── hearing-principles.md           # ヒアリング原則
├── chart-structure.md              # Helm チャート構造ベストプラクティス
├── plan-format.md                  # 計画書フォーマット
├── error-handling.md               # Phase 4 失敗時のみ
├── workload-basics/                # ワークロード自体の基礎 + 能動提案
│   ├── deployment.md
│   ├── daemonset.md
│   ├── statefulset.md
│   ├── job.md
│   └── cronjob.md
└── behavior-patterns/              # 細粒度の振る舞いパターン
    ├── traffic-ingress.md          # 外部受信 (hostPort/Service/Ingress 判断)
    ├── application-config.md       # アプリ設定ファイル生成 (Phase 1 義務)
    ├── config-mount.md             # ConfigMap/Secret マウント
    ├── ephemeral-write.md          # readOnlyRootFilesystem 下の書き込み領域
    ├── health-check.md             # liveness/readiness/startup probe
    ├── replica-scaling.md          # replicaCount, HPA, PDB
    ├── resource-sizing.md          # CPU/メモリ requests/limits, QoS
    ├── data-persistence.md         # PVC, StorageClass
    ├── graceful-shutdown.md        # terminationGracePeriodSeconds, preStop
    ├── observability.md            # メトリクス公開
    ├── cloud-resource-access.md    # IRSA / Workload Identity
    └── (今後追加)
```

---

## Phase 1: ヒアリング (能動的)

### 手順

1. **必須リファレンスを読み込む**:
   - `references/organization-standards.md`
   - `references/hearing-principles.md`
   - `references/chart-structure.md`

2. **リクエストからアプリ特性を抽出**: アプリ種類、入出力、状態保持、HA 要件、特殊配置要件 等

3. **ワークロード種別を確定** (未明示なら必ず質問、推論禁止):
   ```
   ワークロード種別を教えてください:
   ① Deployment (ステートレス Web/API)
   ② DaemonSet (全ノード常駐エージェント)
   ③ StatefulSet (永続化・安定ネットワーク ID 必要)
   ④ Job (一回限りバッチ)
   ⑤ CronJob (定期スケジュールバッチ)
   ```

4. **対象 k8s クラスタのバージョンを確認** (例: "EKS 1.30")

5. **`workload-basics/<workload>.md` を読み込む**: ワークロード特有の能動的提案を実行

6. **アプリ特性から該当する behavior-pattern を抽出し、対応する `behavior-patterns/*.md` を読み込む**:

| アプリ特性 | 該当パターン |
|---|---|
| 外部から受信する、公開する | `traffic-ingress.md` |
| 設定ファイルを使う (rsyslog.conf, nginx.conf 等) | `application-config.md` (必須) + `config-mount.md` |
| ConfigMap/Secret マウントが必要 | `config-mount.md` |
| アプリが /tmp 等に書き込む | `ephemeral-write.md` |
| ヘルスチェックが必要 (httpGet/tcpSocket/exec/grpc) | `health-check.md` |
| Deployment/StatefulSet で複数レプリカ、オートスケール | `replica-scaling.md` |
| CPU/メモリの具体的指定 | `resource-sizing.md` |
| データ永続化 (PVC) | `data-persistence.md` |
| 終了時のバッファドレイン、長時間接続 | `graceful-shutdown.md` |
| Prometheus メトリクス、サービスメッシュ | `observability.md` |
| クラウドリソース (S3, DynamoDB 等) | `cloud-resource-access.md` |

迷ったら読む。複数該当する場合は全て読む。

7. **各 behavior-pattern の「能動的提案」 セクションを実行**:
   - 推奨構成を提示
   - 確認すべき項目を質問 (1 メッセージにまとめる)
   - **ユーザー任せにせず、Claude が初期案を出してから擦り合わせる**

8. **Phase 1 終了条件**:
   - ワークロードと k8s バージョンが確定
   - 全 behavior-pattern について構成が確定 (「未確認」 「未設定」 残しを許さない)
   - **設定ファイル (rsyslog.conf 等) が必要な場合、その中身も確定済み** (`application-config.md` 参照)

---

## Phase 2: 計画提示 + 承諾

1. `references/plan-format.md` を読み込む
2. ワークロードの `templates/<workload>/values.yaml` を読み込む (現在のデフォルト確認)
3. **計画書を生成** (`plan-format.md` 完全準拠):
   - **全項目が「確定済み」** (Phase 1 で擦り合わせ済みのため)
   - 「未設定パラメータ警告」 セクションは **優先度付き** (🔴 設定推奨 / 🟡 環境次第 / ⚪ デフォルト OK)
   - バージョン依存パラメータは、Phase 1 で得たクラスタバージョンで利用可否を `web_search` で確認
   - **矛盾セルフチェック** を実行 (hostPort と Service.NodePort の混同等、各 behavior-pattern の「よくある落とし穴」 を確認)
4. 計画書を表示し、ユーザー承諾を求める
5. **承諾**: 計画を `results/helm-chart-creating-plan-{yyyyMMddHHmm}.md` に保存 → Phase 3
6. **修正要求**: 反映して再承諾
7. **大幅変更**: Phase 1 に戻る

---

## Phase 3: 作成

1. 出力先ディレクトリを確認 (未指定なら質問)
2. `bash scripts/copy-template.sh <workload> <output-dir> <chart-name>` 実行
3. 計画書に従って `values.yaml` 編集
4. 環境別 values の修正があれば `values-{dev,stg,prod}.yaml` も編集
5. `Chart.yaml` の `description` と `appVersion` を更新
6. 計画書に設定ファイル (rsyslog.conf 等) があれば、対応する ConfigMap テンプレートを作成

**原則**: テンプレートを直接書き換えない (必ず copy-template.sh 経由)。計画にない変更を加えない。

---

## Phase 4: 検証

1. `bash scripts/validate-chart.sh <chart-dir>` 実行
2. 成功 → 完了報告
3. 失敗 → `references/error-handling.md` を読んで原因分析 → Phase 3 修正
4. 同じエラーが 3 回続けば Phase 1 に戻る

---

## 出力の一貫性を保つための鉄則

- リファレンスから逸脱しない
- `scripts/` のスクリプトを必ず使う
- 計画にない変更を加えない
- 承諾プロセスを省略しない
- ワークロードを推論しない
- k8s 技術用語を直接聞かない
- **設定ファイル中身を計画書で初出しない** (Phase 1 で確定する)
- **「未設定」 のまま計画書に載せない** (能動的提案の責務)
- **組織標準に違反しない** (`organization-standards.md` を優先)
