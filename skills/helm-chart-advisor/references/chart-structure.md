# チャートの基本構造と命名規則

## チャート名の命名規則

**設定内容**: チャート名は小文字英字で始め、小文字英字・数字・ハイフンのみを使用する。アンダースコア・ドット・大文字は使用しない。チャートを格納するディレクトリ名はチャート名と一致させる。

**目的と効果**: Helm のテンプレートエンジンはハイフン以外の区切り文字で問題を起こす可能性があるため、命名規則を統一することで、チャートリポジトリ全体での一貫性を保ち、チーム内外でのチャート検索・共有を容易にする。ディレクトリ名の一致は Helm のパッケージングフォーマットの要件でもある。

## SemVer 2 によるバージョニング

**設定内容**: `Chart.yaml` の `version` フィールドには SemVer 2（MAJOR.MINOR.PATCH）を使用する。後方互換性を壊す変更は MAJOR、機能追加は MINOR、バグ修正は PATCH をインクリメントする。

**目的と効果**: チャート利用者がバージョン番号だけでアップグレードの影響範囲を判断でき、依存関係の解決時にも `^` や `~` 等の範囲指定が正しく機能する。

## `helm create` によるスキャフォールド活用

**設定内容**: 新規チャートは `helm create <chart-name>` で生成し、生成されたファイル構造をベースに開発を始める。

**目的と効果**: ゼロからYAMLを手書きする場合に比べ、ベストプラクティスに沿った構造が初期状態で得られる。_helpers.tpl にはフルネーム生成やラベル生成のヘルパーテンプレートが含まれ、重複コードを排除できる。

### スキャフォールドの標準ファイル構造

`helm create` が生成する以下の構造を、すべての Helm chart が備えるべき基準として扱う。手動で作成されたチャートであっても、この構造と差分がないことを目指す。

```
<chart-name>/
├── .helmignore                    # パッケージング時の除外ルール
├── Chart.yaml                     # チャートメタデータ
├── values.yaml                    # デフォルト値
├── charts/                        # 依存チャート格納ディレクトリ
└── templates/
    ├── _helpers.tpl               # 共通ヘルパーテンプレート
    ├── deployment.yaml            # ワークロード定義
    ├── hpa.yaml                   # HorizontalPodAutoscaler
    ├── ingress.yaml               # Ingress
    ├── service.yaml               # Service
    ├── serviceaccount.yaml        # ServiceAccount
    ├── NOTES.txt                  # インストール後の案内メッセージ
    └── tests/
        └── test-connection.yaml   # 接続テスト
```

ワークロードの種類によってテンプレートファイルは異なる場合がある（例: DaemonSet なら `daemonset.yaml`、StatefulSet なら `statefulset.yaml`）が、それ以外のファイル（.helmignore, _helpers.tpl, NOTES.txt, serviceaccount.yaml, tests/ 等）はワークロードの種類に関わらず存在すべきである。

### スキャフォールド差分チェック

レビューや編集で既存チャートを扱う際、上記の標準構造と比較して不足しているファイルがあれば指摘する。よくある不足パターン:

- **.helmignore がない**: パッケージに不要なファイル（.git, テストデータ等）が含まれるリスクがある
- **_helpers.tpl がない**: チャート名やラベルの生成が各テンプレートに散在し、名前の不整合が起きやすい
- **NOTES.txt がない**: `helm install` 後にユーザーへの案内（アクセス方法、次のステップ等）が表示されない
- **serviceaccount.yaml がない**: デフォルトの ServiceAccount が使用され、RBAC の最小権限原則に反する
- **tests/ がない**: `helm test` による動作確認ができない
- **hpa.yaml がない**: HPA を有効にする場合に後から追加が必要になる（values で `autoscaling.enabled: false` としておけば影響なし）
- **ingress.yaml がない**: Ingress を有効にする場合に後から追加が必要になる（同上）

