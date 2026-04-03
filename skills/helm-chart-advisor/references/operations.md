# helm upgrade/install の運用パラメータ

## `--atomic` フラグ

**設定内容**: `helm upgrade --install --atomic` を使用する。

**目的と効果**: アップグレードが失敗した場合に自動的にロールバックする。`--wait` フラグも暗黙的に有効化され、すべてのPod・PVC・Service がready状態になるまで待機する。初回インストールで失敗した場合はリリース自体が削除される。

## `--timeout` フラグ

**設定内容**: `--timeout 10m` のようにデプロイのタイムアウトを設定する。デフォルトは 5 分。

**目的と効果**: 大規模アプリケーション（JVM起動、DB マイグレーション等）でデフォルトの5分では不十分な場合がある。タイムアウトはチャート内の全リソースに対してグローバルに適用される。

## `--history-max` フラグ

**設定内容**: `--history-max 10` のようにリリース履歴の保持数を制限する。

**目的と効果**: Helm はリリースごとにリビジョンを Kubernetes Secret として保存するため、履歴が無制限に蓄積すると etcd のストレージを圧迫する。10〜20 程度に制限する。

## `--cleanup-on-fail` フラグ

**設定内容**: `helm upgrade --cleanup-on-fail` を使用する。

**目的と効果**: アップグレード失敗時に、そのアップグレードで新たに作成されたリソースを削除する。`--atomic` がロールバックであるのに対し、こちらはゴミリソースの掃除に特化している。

## `helm upgrade --install`（べき等なデプロイ）

**設定内容**: 常に `helm upgrade --install` を使用する。

**目的と効果**: リリースが存在しない場合はインストール、存在する場合はアップグレードを行い、べき等な操作を実現する。CI/CD で「すでにインストール済みかどうか」の条件分岐が不要になる。

## `--description` フラグ

**設定内容**: `helm upgrade --description "Upgrade to fix CVE-2026-1234"` のようにリリースの説明を付与する。

**目的と効果**: `helm history` で各リビジョンの変更理由を確認でき、障害発生時の原因特定やロールバック判断に役立つ。

## 本番デプロイコマンドの推奨構成

```bash
helm upgrade --install my-app ./charts/my-app \
  --namespace production \
  --create-namespace \
  -f values/production.yaml \
  --set image.tag=${GITHUB_SHA} \
  --atomic \
  --timeout 10m \
  --history-max 10 \
  --description "Deploy ${GITHUB_SHA::8} from ${GITHUB_REF_NAME}"
```

---

# CI/CD パイプラインへの統合

## 段階的バリデーション

**設定内容**: CI パイプラインに以下のステージを必須として構成する。

1. **`helm lint`**: 構文エラー、values.schema.json 違反を検出
2. **`helm template` + kubeconform**: レンダリング結果の Kubernetes API スキーマ検証
3. **`helm install --dry-run=server`**: クラスタ接続を含むサーバーサイドの事前検証
4. **`helm test`**: デプロイ後のスモークテスト

**目的と効果**: 各段階で異なるレイヤーの問題を検出する。`helm lint` はチャート構造の問題、kubeconform は Kubernetes マニフェストの妥当性、dry-run はクラスタ固有の制約を検証する。

---

# シークレット管理

## helm-secrets プラグイン + SOPS

**設定内容**: `helm plugin install https://github.com/jkroepke/helm-secrets` でプラグインをインストールし、Mozilla SOPS で values ファイルを暗号化して Git にコミットする。

**目的と効果**: シークレットを Git で管理しつつ、平文での保存を防止する。AWS KMS、GCP KMS、Azure Key Vault、PGP をバックエンドとして利用可能。

## External Secrets Operator / Sealed Secrets

**設定内容**: External Secrets Operator で AWS Secrets Manager / HashiCorp Vault 等から動的にKubernetes Secretを生成する。または Sealed Secrets で kubeseal による暗号化 SealedSecret をGitにコミットする。

**目的と効果**: helm-secrets がデプロイ時に復号するのに対し、External Secrets Operator はクラスタ内のコントローラーが継続的に外部ストアと同期する。

---

# テストの実装

## `helm test` によるスモークテスト

**設定内容**: `templates/tests/` にテスト用Podを配置し、`helm.sh/hook: test` アノテーションを付与する。

**目的と効果**: デプロイ後にアプリケーションが正常に動作していることを自動検証する。テストPodのコンテナが終了コード 0 で終了すれば成功。

## helm-unittest による単体テスト

**設定内容**: helm-unittest プラグインでBDDスタイルのユニットテストを作成する。

**目的と効果**: クラスタに接続せずにテンプレートのレンダリング結果を検証できる。

## chart-testing（ct）ツール

**設定内容**: `ct lint --charts ./mychart` と `ct install --charts ./mychart` で lint + install テストを自動化する。

**目的と効果**: GitHub Actions の `helm/chart-testing-action` と統合して PR ごとに自動テストを実行できる。

