# OpenSpec on Docker for GitHub Copilot

[OpenSpec](https://github.com/Fission-AI/OpenSpec) の CLI(`openspec`)を Docker コンテナで運用するためのセットアップ手順です。OpenSpec は brownfield(既存コードベース)を第一に設計された spec-driven development フレームワークで、`openspec/specs/` 配下に永続的な機能仕様を蓄積し、AI コーディングアシスタントが常時参照できる状態を作ります。

## 概要

OpenSpec は次の二層構造で機能仕様を管理します:

- **`openspec/specs/<capability>/spec.md`** — 現在の真実(永続的な機能仕様)
- **`openspec/changes/<change-name>/`** — 提案中の変更(アーカイブ後に specs/ にマージされる)

各 capability の spec は ADDED/MODIFIED/REMOVED の delta 操作で更新されるため、変更履歴を保ちつつ仕様の整合性を維持できます。

CLI 自体はコンテナ内に閉じ込めつつ、初期化や CLI コマンドの結果はマウントされたプロジェクトディレクトリに永続化されるため、日常開発(Copilot Chat でのスラッシュコマンド利用)はコンテナを意識せずに進められます。

## 前提条件

- Docker(Linux / macOS / WSL2 のいずれか)
- VS Code + GitHub Copilot 拡張(プロジェクトを編集する側)
- **重要**: GitHub Copilot のスラッシュコマンドは **IDE 拡張(VS Code、JetBrains、Visual Studio)でのみ動作** します。GitHub Copilot CLI は現時点で `.github/prompts/*.prompt.md` を認識しないため、ターミナル単独運用には適しません(公式ドキュメントの [Supported Tools](https://github.com/Fission-AI/OpenSpec/blob/main/docs/supported-tools.md) を参照)。

## Dockerfile

リポジトリルートに以下の `Dockerfile` を配置します。

```dockerfile
# syntax=docker/dockerfile:1.7
FROM node:24-slim

# OpenSpec は Node.js 20.19.0 以上を要求
# node:24 は 2025年10月から Active LTS(コードネーム Krypton)で、Active LTS は 2026年10月まで
# https://github.com/Fission-AI/OpenSpec#quick-start
# https://github.com/nodejs/Release

# OpenSpec を npm でグローバルインストール(イメージビルド時、root として実施)
# 最新バージョンは https://www.npmjs.com/package/@fission-ai/openspec で確認
RUN npm install -g @fission-ai/openspec@latest

# ホストとの UID/GID 衝突を避けるため、既存の node ユーザーの UID/GID を調整
ARG USER_ID=1000
ARG GROUP_ID=1000
RUN if [ "${GROUP_ID}" != "1000" ]; then groupmod -g ${GROUP_ID} node; fi \
    && if [ "${USER_ID}" != "1000" ]; then usermod -u ${USER_ID} -g ${GROUP_ID} node; fi

# OpenSpec のグローバル設定ディレクトリを node 所有で事前作成
# (ホスト側ディレクトリを bind mount する際の権限問題を防ぐため)
# OpenSpec のデフォルト設定パスは ~/.config/openspec/config.json
RUN mkdir -p /home/node/.config/openspec \
    && chown -R node:node /home/node/.config

USER node
WORKDIR /workspace

# テレメトリーを無効化(任意。CI 環境では自動で無効化される)
# https://github.com/Fission-AI/OpenSpec#telemetry
ENV OPENSPEC_TELEMETRY=0

CMD ["bash"]
```

## セットアップ

### 1. イメージのビルド

```bash
docker build -t openspec \
  --build-arg USER_ID=$(id -u) \
  --build-arg GROUP_ID=$(id -g) \
  .
```

### 2. シェル関数の登録(任意・推奨)

毎回長い `docker run` を打たないよう、`~/.bashrc` または `~/.zshrc` に以下のラッパー関数を追加します。

```bash
openspec() {
  # OpenSpec のグローバル設定をプロジェクト配下に永続化
  # (Docker に作らせると root 所有になるため、事前にホスト側で作成)
  mkdir -p "$(pwd)/.config/openspec"

  docker run -it --rm \
    -v "$(pwd):/workspace" \
    -v "$(pwd)/.config/openspec:/home/node/.config/openspec" \
    openspec \
    openspec "$@"
}
```

シェルを再起動するか `source ~/.bashrc` を実行すると、ホスト側で `openspec` コマンドを直接呼べるようになります(裏側でコンテナが起動します)。

**ボリュームマウントの意味:**
- 1 つ目(`$(pwd):/workspace`):プロジェクト全体をコンテナに見せる(spec ファイルや変更管理に使用)
- 2 つ目(`$(pwd)/.config/openspec:/home/node/.config/openspec`):OpenSpec のグローバル設定(profile、delivery mode、選択中のワークフロー等)をプロジェクト配下に永続化。これにより、`openspec config profile` で行った設定が `docker run --rm` で消えず、プロジェクト単位で独立して保持されます

OpenSpec は CLI 内で `git init` などを実行しないため、Spec Kit と異なり `~/.gitconfig` のマウントは不要です。

### 3. `.gitignore` への追加(任意)

`.config/openspec/` を git で追跡したくない場合は、プロジェクトの `.gitignore` に以下を追加します。

```
.config/openspec/
```

逆にチームで OpenSpec の設定を共有したい場合は、追加せずにコミットする選択肢もあります(個人事業の場合は通常追跡しない方が単純です)。

## プロジェクトの初期化

新規 / 既存どちらのプロジェクトでも、対象ディレクトリで以下を実行します。

```bash
cd /path/to/your-project
openspec init --tools github-copilot --profile core --force
```

各フラグの意味([CLI Reference](https://github.com/Fission-AI/OpenSpec/blob/main/docs/cli.md#openspec-init)より):

- `--tools github-copilot`:GitHub Copilot 用のスキル / プロンプトファイルを生成(対話プロンプトを回避)
- `--profile core`:デフォルトの `core` プロファイルを明示指定(propose / explore / apply / archive の 4 コマンド)
- `--force`:既存ファイルがある場合の確認をスキップして自動クリーンアップ

成功すると以下のディレクトリ構造が作成されます。

```
your-project/
├── openspec/
│   ├── specs/                                # 機能仕様の永続置き場(現在の真実)
│   ├── changes/                              # 変更提案(一時的、archiveでマージされる)
│   └── config.yaml                           # プロジェクト設定
└── .github/
    ├── skills/                               # OpenSpec スキル(クロスツール標準)
    │   ├── openspec-propose/SKILL.md
    │   ├── openspec-explore/SKILL.md
    │   ├── openspec-apply-change/SKILL.md
    │   └── openspec-archive-change/SKILL.md
    └── prompts/                              # ★ Copilot IDE のスラッシュコマンド本体
        ├── opsx-propose.prompt.md
        ├── opsx-explore.prompt.md
        ├── opsx-apply.prompt.md
        └── opsx-archive.prompt.md
```

`.github/prompts/` 配下のファイルが VS Code の Copilot Chat にスラッシュコマンドとして自動認識されます。

## 日常のワークフロー

初期化後は **Copilot Chat 上だけで作業が完結** します。コンテナを再度起動する必要はありません(VS Code は `.github/prompts/` を直接読み取るため)。

### スラッシュコマンド(core プロファイル)

[Commands リファレンス](https://github.com/Fission-AI/OpenSpec/blob/main/docs/commands.md)より、Copilot IDE では **ハイフン区切り** のシンタックスを使用します(Claude Code の `/opsx:propose` とは異なる点に注意)。

| コマンド | 役割 |
|---|---|
| `/opsx-propose` | 変更を作成し、計画アーティファクト(proposal、specs、design、tasks)を一括生成 |
| `/opsx-explore` | 変更にコミットする前に、コードベースを調査・検討 |
| `/opsx-apply` | tasks.md に従って実装を実行 |
| `/opsx-archive` | 完了した変更をアーカイブし、delta を `openspec/specs/` にマージ |

### 推奨フロー

新機能を追加する / 既存機能を変更するときの流れ:

1. **(任意)** Copilot Chat で `/opsx-explore` を実行し、関連する既存仕様や実装を調査します。要件が曖昧なときに特に有効です。
2. `/opsx-propose <変更名>` で変更を作成します。例:`/opsx-propose add-webhook-notification`
   - `openspec/changes/<変更名>/` 配下に proposal.md / specs/ / design.md / tasks.md が生成されます
   - specs/ には capability 単位で delta(ADDED/MODIFIED/REMOVED)が記述されます
3. 生成された artifact をレビューし、必要なら手動で編集します。
4. `/opsx-apply` で tasks.md のチェックリストに沿って実装を進めます。
5. `/opsx-archive` で変更を確定します:
   - delta が `openspec/specs/<capability>/spec.md` にマージされる
   - 変更フォルダが `openspec/changes/archive/YYYY-MM-DD-<変更名>/` に移動する
   - 以後、AI は capability の仕様を参照する際にマージ後の `specs/<capability>/spec.md` を読む

### 既存機能の仕様化(brownfield 対応)

既存コードベースに OpenSpec を導入する場合、**全機能を一度に逆起こしせず**、変更や調査の単位で incremental に仕様化するのが OpenSpec の推奨アプローチです。

```
既存機能を変更する必要が発生
        ↓
/opsx-explore で既存実装を調査
        ↓
/opsx-propose <変更名> で変更を提案(関連 capability の delta を作成)
        ↓
/opsx-apply で実装
        ↓
/opsx-archive で specs/<capability>/ にマージ
        ↓
触ったところから順に specs/ が育っていく
```

時間とともに、頻繁に触る領域から `openspec/specs/` 配下に「○○機能は□□の処理を行う」という仕様が蓄積されていきます。

## 拡張ワークフロー(任意)

`core` プロファイル以外の追加コマンド(`/opsx-new`、`/opsx-continue`、`/opsx-ff`、`/opsx-verify`、`/opsx-sync`、`/opsx-bulk-archive`、`/opsx-onboard`)を使いたい場合は、グローバル設定でプロファイルを変更します。

```bash
# グローバル設定の対話的編集(コンテナ内で実行)
openspec config profile

# プロジェクトの prompts / skills を再生成
openspec update
```

ただし `openspec config` の設定はプロジェクト配下の `.config/openspec/` に保存されます(セットアップで bind mount を構成済みのため)。コンテナ再起動後も設定は保持され、プロジェクトごとに独立した設定を持てます。

詳細は [Commands リファレンス](https://github.com/Fission-AI/OpenSpec/blob/main/docs/commands.md#expanded-workflow-commands-custom-workflow-selection)を参照。

## メンテナンス

以下のコマンドはコンテナ経由で実行する必要があります(ラッパー関数を登録していれば直接 `openspec ...` で OK)。

### CLI コマンドリファレンス

[CLI Reference](https://github.com/Fission-AI/OpenSpec/blob/main/docs/cli.md) の主要コマンド:

```bash
# 現在の変更とスペックを一覧
openspec list                 # アクティブな変更を表示
openspec list --specs         # 永続化された仕様を表示

# 変更や仕様の中身を表示
openspec show <change-or-spec-name>

# バリデーション(構造的な問題を検出)
openspec validate                  # 対話的
openspec validate --all --strict   # すべてを厳格モードで検証

# 変更の進捗状況を確認
openspec status --change <change-name>

# 変更をアーカイブ(スラッシュコマンドの代替)
openspec archive <change-name> --yes
```

### OpenSpec のアップグレード

新しいバージョンの OpenSpec に追従するには、まずコンテナイメージを再ビルドし、その後プロジェクトを更新します。

```bash
# 1. イメージを再ビルド(openspec が最新版になる)
docker build -t openspec \
  --build-arg USER_ID=$(id -u) \
  --build-arg GROUP_ID=$(id -g) \
  --no-cache .

# 2. プロジェクトの prompts / skills を更新
cd /path/to/your-project
openspec update
```

`openspec update` は既存の `openspec/specs/` や `openspec/changes/` には触れず、AI ツール向けの指示ファイルのみ再生成します(出典: [README - Updating OpenSpec](https://github.com/Fission-AI/OpenSpec#updating-openspec))。

### バージョン固定する場合

CI/CD で再現性を担保したい場合や、メジャー更新前に動作を凍結したい場合は、Dockerfile の `npm install` 行に明示的なバージョンを指定します。

```dockerfile
RUN npm install -g @fission-ai/openspec@1.3.1
```

## トラブルシューティング

### スラッシュコマンドが Copilot Chat に表示されない

1. **VS Code を完全再起動**します(ウィンドウのリロードでは不十分な場合があります)。
2. **正しいプロジェクトディレクトリを開いている**か確認します。`.github/prompts/` がワークスペースルート直下にある必要があります。
3. **GitHub Copilot 拡張のバージョン**を確認し、必要なら更新します。
4. **プロンプトファイルが空でない**ことを確認します:

   ```bash
   for f in .github/prompts/opsx-*.prompt.md; do
     wc -c "$f"
   done
   ```

5. それでも認識されない場合は `openspec update` で再生成を試します(出典: [Commands リファレンス - Troubleshooting](https://github.com/Fission-AI/OpenSpec/blob/main/docs/commands.md#troubleshooting))。

### `Permission denied` が発生する

ビルド時に渡した `USER_ID` / `GROUP_ID` がホストの実 UID/GID と一致していない可能性があります。再ビルドしてください。

```bash
docker build -t openspec \
  --build-arg USER_ID=$(id -u) \
  --build-arg GROUP_ID=$(id -g) \
  --no-cache .
```

### `openspec` を Copilot CLI で使いたい

GitHub Copilot CLI は現時点で `.github/prompts/*.prompt.md` を認識しないため、`/opsx-propose` 等のスラッシュコマンドは動作しません。これは OpenSpec 公式の [Supported Tools](https://github.com/Fission-AI/OpenSpec/blob/main/docs/supported-tools.md) で明記された制限です。

回避策としては:
- VS Code / JetBrains / Visual Studio の Copilot 拡張を併用する
- OpenSpec の代わりに直接 `openspec/specs/<capability>/spec.md` を読ませて作業する

### 設定ファイルのパスを別の場所に変えたい

デフォルトでは設定は `<project>/.config/openspec/config.json` に保存されます。別の場所にしたい場合は、Dockerfile に `XDG_CONFIG_HOME` を設定してパスを変更できます:

```dockerfile
# 例: コンテナ内のパスを /workspace/.openspec-cli/ に変更
ENV XDG_CONFIG_HOME=/workspace/.openspec-cli
```

その上でラッパー関数のマウント先パスも対応する形に変更します。なお、この方法は OpenSpec ソースコード上は対応している(XDG Base Directory 仕様準拠)ものの、公式ユーザードキュメントには明示記載がないため、変更後は `openspec config path` で実際のパスを確認してください。

## 制限事項

- **GitHub Copilot CLI 非対応**:スラッシュコマンドは IDE 拡張のみで動作します(VS Code、JetBrains、Visual Studio)。
- **`openspec view`(対話ダッシュボード)**:`-it` フラグで TTY を確保した状態で実行する必要があります。
- **コマンド構文の差異**:Copilot IDE では `/opsx-propose` のようにハイフン区切りです。Claude Code 等の `/opsx:propose`(コロン区切り)とは異なります。
- **設定ファイルのパス**:OpenSpec は `~/.config/openspec/config.json`(または `$XDG_CONFIG_HOME/openspec/config.json`)を読み書きします。本 README ではこれをプロジェクト配下に bind mount して永続化していますが、このパスは公式ユーザードキュメントには明記されておらず、ソースコードレベルで XDG Base Directory 仕様に準拠している点に基づいています。OpenSpec のメジャーアップデートで変更される可能性があるため、`openspec config path` で随時確認することを推奨します。

## 参考リンク

### 公式ドキュメント(本 README の根拠)

- [OpenSpec リポジトリ](https://github.com/Fission-AI/OpenSpec)
- [公式サイト](https://openspec.dev/)
- [Installation](https://github.com/Fission-AI/OpenSpec/blob/main/docs/installation.md) — Node.js 20.19.0 以上の要件
- [CLI Reference](https://github.com/Fission-AI/OpenSpec/blob/main/docs/cli.md) — `openspec init` の全フラグ仕様
- [Commands](https://github.com/Fission-AI/OpenSpec/blob/main/docs/commands.md) — スラッシュコマンドの詳細(ツール別シンタックス含む)
- [Supported Tools](https://github.com/Fission-AI/OpenSpec/blob/main/docs/supported-tools.md) — `github-copilot` ツール ID と Copilot CLI の制限
- [Concepts](https://github.com/Fission-AI/OpenSpec/blob/main/docs/concepts.md) — delta 仕様、requirement、scenario の書き方
- [Workflows](https://github.com/Fission-AI/OpenSpec/blob/main/docs/workflows.md) — ワークフローパターン

### 関連リソース

- [npm: @fission-ai/openspec](https://www.npmjs.com/package/@fission-ai/openspec) — 最新バージョンの確認
- [Node.js Docker 公式イメージ](https://hub.docker.com/_/node) — ベースイメージの選択
- [DeepWiki: Fission-AI/OpenSpec](https://deepwiki.com/Fission-AI/OpenSpec) — ソースコード解析(設定ファイルパスの根拠)