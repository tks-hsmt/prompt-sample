# OCI レジストリによるチャート配布

## OCI レジストリへの移行

**設定内容**: Helm 3.8+ / Helm 4 で GA の OCI サポートを使用し、`helm push` でECR・GCR・ACR・GHCR等にチャートを格納する。

**目的と効果**: 従来の ChartMuseum に比べ、コンテナイメージとチャートの認証・認可・脆弱性スキャン・アクセスコントロール・レプリケーションを統一基盤で管理できる。`helm repo add` / `helm repo update` が不要になる。

## チャートの署名と検証

**設定内容**: `helm package --sign` でGPG鍵によりチャートに署名し、利用者は `--verify` で検証する。

**目的と効果**: チャートのサプライチェーン攻撃（改ざんされたチャートの配布）を防止する。

---

# Helmfile による複数リリース管理

## 宣言的リリース管理

**設定内容**: `helmfile.yaml` で全リリースの設定を一元管理し、`helmfile diff` で変更差分を確認した上で `helmfile sync` で適用する。

**目的と効果**: 10個以上のリリースを複数環境で管理する場合に、個別の `helm upgrade` コマンドの羅列では管理が破綻する。Helmfile は環境別 values、シークレット統合、リリース間の依存関係、並列デプロイをサポートする。

---

# GitOps（ArgoCD）との統合

## ArgoCD + OCI レジストリ

**設定内容**: ArgoCD Application で `repoURL` に OCI レジストリを指定し、`syncPolicy.automated` で自動同期を有効化する。`selfHeal: true` でクラスタ状態の自動修復、`prune: true` で不要リソースの自動削除を設定する。

**目的と効果**: Git リポジトリを信頼の源泉とし、クラスタ状態の drift を自動検知・修復する。OCI レジストリとの統合により、チャートの配布とデプロイを一気通貫で管理できる。

---

# ドキュメンテーション

## helm-docs による自動生成

**設定内容**: `helm-docs` を使い、`values.yaml` のコメントと `Chart.yaml` から README.md を自動生成する。pre-commit hook と統合して常に最新の状態を維持する。

**目的と効果**: values.yaml への変更がREADMEに自動反映され、ドキュメントの陳腐化を防止する。

## NOTES.txt

**設定内容**: `templates/NOTES.txt` にインストール後の手順（アクセスURL取得コマンド、初期パスワード取得方法等）を記述する。

**目的と効果**: `helm install` 完了後に自動表示され、利用者が次のステップを即座に把握できる。

---

# Helm 4 への対応

## Server-Side Apply

**設定内容**: Helm 4 は Kubernetes の Server-Side Apply と統合し、フィールドの所有権管理を改善している。

**目的と効果**: Helm 3 の client-side 3-way merge では ArgoCD 等の GitOps ツールとフィールド所有権が競合し、configuration drift が発生することがあった。Server-Side Apply ではフィールドごとの所有者が API サーバー側で管理され、この問題が解消される。

## 後方互換性

**設定内容**: Helm 4 は v2 API チャート（Helm 3 のチャート）との後方互換性を維持している。

**目的と効果**: 既存のチャートをそのまま Helm 4 で使用でき、段階的な移行が可能。

