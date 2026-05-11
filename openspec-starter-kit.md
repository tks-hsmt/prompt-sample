# OpenSpec 運用スターターキット

OpenSpec を導入したプロジェクトで、AI コーディングアシスタントが
「○○の機能は□□という仕様である」を常に参照できる状態を作るためのガイドです。

OpenSpec 1.0 以降の設計に準拠しています。

## プロジェクト全体のファイル構成

このスターターキットを使った OpenSpec プロジェクトは、次の構成になります。

```
your-project/                          ← プロジェクトのルートディレクトリ
│
├── openspec/                          ← OpenSpec が管理する領域
│   ├── config.yaml                    ★ プロジェクト全体の規約と AI への指示
│   │                                    (本スターターキットの「1」で作成)
│   │
│   ├── specs/                         ★ capability ごとの永続的な現状仕様
│   │   ├── <capability-1>/
│   │   │   └── spec.md                  運用しながら 1 つずつ蓄積していく
│   │   ├── <capability-2>/
│   │   │   └── spec.md
│   │   └── ...                          書き方は feature-spec-template.md を参照
│   │
│   └── changes/                       ★ 進行中の変更と完了履歴
│       ├── <change-name>/             (/opsx-propose で作成される)
│       │   ├── proposal.md              なぜ・何を変えるか
│       │   ├── design.md                技術的アプローチ
│       │   ├── tasks.md                 実装チェックリスト
│       │   └── specs/                   delta(ADDED/MODIFIED/REMOVED)
│       └── archive/                   (/opsx-archive 後に移動)
│           └── YYYY-MM-DD-<name>/
│
├── docs/                              ★ 補助ファイル(必要に応じて作成)
│   ├── architecture/
│   │   └── system-overview.md           全体システム構成図(Mermaid)
│   ├── conventions.md                   コーディング規約の詳細
│   ├── domain-glossary.md               ドメイン用語集
│   └── references/                      リソース一覧(YAML)など
│
└── (実装ファイル)                      ← プロジェクト本体のコード
```

### 各要素の役割

| 要素 | 役割 | 作成タイミング |
|---|---|---|
| `openspec/config.yaml` | プロジェクト全体の規約と AI への指示。`context` は全 artifact に毎回自動注入される | 初期セットアップ時 |
| `openspec/specs/<capability>/spec.md` | 個別 capability の永続的な現状仕様 | 機能ごとに `/opsx-archive` 後に蓄積 |
| `openspec/changes/<change-name>/` | 進行中の変更の作業領域 | `/opsx-propose` で自動作成 |
| `openspec/changes/archive/` | 完了した変更の履歴 | `/opsx-archive` で自動移動 |
| `docs/` 配下 | 補助ファイル。`openspec/config.yaml` の `context` から参照する | 必要に応じて手動作成 |

### このスターターキットに含まれるファイル

| ファイル | 用途 |
|---|---|
| `openspec-starter-kit.md`(本ファイル) | 全体運用方針、`openspec/config.yaml` のテンプレート、プロンプトテンプレート |
| `feature-spec-template.md` | `openspec/specs/<capability>/spec.md` を書く際の詳細テンプレート(EARS、Scenario、NFR の記法を含む) |

---

## OpenSpec 1.0+ の設計

OpenSpec 1.0 では、AI への命令は次の 3 層から動的にアセンブルされます。

```
context (プロジェクト全体の文脈)
  +
rules  (artifact 別の制約)
  +
templates (出力構造)
  ↓
AI が CLI から受け取り、artifact を生成
```

これらはすべて `openspec/config.yaml` に集約され、AI が `/opsx-propose` を実行する
たびに自動的に注入されます。1.0 以前にあった `project.md`、`AGENTS.md`、
`CLAUDE.md`、`.cursorrules` などのツール固有設定ファイルは廃止されました。

### 各ファイルの役割

```
┌────────────────────────────────────────────────────────────────────┐
│  ファイル                          書く内容          AI への伝達   │
├────────────────────────────────────────────────────────────────────┤
│  openspec/config.yaml              プロジェクト      毎回自動注入  │
│   - context                        全体の不変的                    │
│   - rules                          な文脈と規約                    │
│                                                                    │
│  openspec/specs/<capability>/      capability ごと   AI が該当変更 │
│    spec.md                         の現状仕様        時に参照      │
│                                                                    │
│  openspec/changes/<change-name>/   変更の作業領域    変更作業中に  │
│    (proposal、design、tasks、      (一時的)          参照          │
│     delta specs)                                                   │
└────────────────────────────────────────────────────────────────────┘
```

**役割分担の原則**:

- プロジェクト全体に共通する話 → `openspec/config.yaml`
- 個別 capability の振る舞い → 該当する `openspec/specs/<capability>/spec.md`
- 変更ごとの設計判断 → 該当する change の `openspec/changes/<change-name>/design.md`

役割を超えた情報を混入させると、AI が誤った文脈で判断する原因になります。

---

## 1. `openspec/config.yaml`

プロジェクト全体の規約と AI への指示を集約する、唯一の中心ファイルです。
`context` は **全 artifact 生成時に自動注入** されるため、簡潔さが重要です。

### 完成系テンプレート

```yaml
schema: spec-driven

context: |
  # 言語と表記ルール
  Language: Japanese
  すべての成果物は日本語で作成してください。
  ただし以下は英語のまま使用してください:
  - "### Requirement:" "#### Scenario:" のセクション見出し
  - GIVEN / WHEN / THEN / AND(BDD のキーワード)
  - SHALL / MUST / SHOULD / MAY / MUST NOT(RFC 2119 の規範語)
  - When / While / If / Where / Otherwise(EARS のパターン識別子)

  # プロジェクト定義
  <プロジェクト全体の目的を 1〜2 文で記述>

  # 技術スタック
  - 言語: <例: TypeScript 5.3、Go 1.22>
  - ランタイム: <例: Node.js 24 LTS>
  - 主要フレームワーク: <例: NestJS 10、FastAPI 0.115>
  - インフラ: <例: Kubernetes (Amazon EKS 1.32)、Terraform 1.7>
  - データストア: <例: PostgreSQL 16、Redis 7>

  # 不変の原則(最重要のみ)
  - 設定はコードと分離する
  - 障害時もメインの処理パイプラインは停止しない
  - すべての変更は監視・観測可能であること

  # 詳細情報の参照先
  - 全体システム構成: docs/architecture/system-overview.md
  - コーディング規約: docs/conventions.md
  - ドメイン用語: docs/domain-glossary.md

  # 共通の品質要求
  - すべての requirement は測定可能・検証可能な形式で記述する
  - 数値が必要な箇所では具体的な値を含める
  - 既存実装と矛盾する spec を作らない(矛盾する場合は MODIFIED で明示)
  - 既存の openspec/specs/ 配下の spec を参考にして同じスタイルで生成する

rules:
  proposal:
    - 目的、変更内容、影響範囲を明確に記述する
    - 影響を受ける既存 capability を「Affected Capabilities」として列挙する
    - 既存資産への影響(後方互換性、移行手順)を必ず明記する
    - ロールバック手順を含める

  specs:
    # frontmatter
    - YAML frontmatter を必ず含める
    - frontmatter には capability_id、capability_name、version、status、last_updated、owners、related_files を含める
    - 関係性がある場合は frontmatter に depends_on、consumed_by、verified_by を追加する

    # 本文構造
    - "## 目的" には 2〜4 文で「なぜこの機能が存在するか」を書く(What ではなく Why)
    - "## スコープ" には対象範囲と対象外を両方書く
    - 機能要件は EARS 形式で書く
    - SHALL / MUST / SHOULD / MAY を RFC 2119 に従って使い分ける
    - 各 Requirement には Scenario を 1 つ以上含める
    - 複雑な要件には #### Rationale セクションで根拠を書く
    - 非機能要件は性能・信頼性・セキュリティ・観測性・保守性のカテゴリで分類する
    - すべての非機能要件には測定可能な数値を含める
    - 外部システムとの I/O がある場合は "## インターフェース" セクションを書く
    - "## 制約事項" には理由も併記する
    - "## 対象外" には「やらないこと」とその理由を書く

    # 構成情報の表現
    - データフローや状態遷移がある場合、spec.md 内に Mermaid 図で記述する
    - capability のスコープを適切に小さく保ち、spec.md が肥大化しないようにする

  design:
    - 採用した技術の選定理由を必ず明記する
    - 代替案を 1 つ以上検討し、なぜそれを採用しなかったかを書く
    - 既存アーキテクチャとの整合性を確認するセクションを含める
    - 障害シナリオと対処方法を含める
    - 監視・運用観点を含める(メトリクス、アラート、ログ)
    - 複雑な処理フローには Mermaid 形式でシーケンス図を含める

  tasks:
    - 各タスクは独立に実装・テスト可能な単位に分割する
    - タスクには依存関係がある場合、依存元タスクの番号を明記する
    - 単体テスト、統合テストの作成タスクを必ず含める
    - 本番反映前の検証手順をタスクとして含める
    - 影響の大きい変更(IAM、本番設定など)は実装前にユーザー確認を求めるよう明記する
```

### 補助ファイルの配置場所

`config.yaml` の `context` から参照する補助ファイルは、内容に応じて適切な
フォーマットで `docs/` 配下に配置します。

| 情報の種類 | 推奨フォーマット | 配置場所の例 |
|---|---|---|
| 全体システム構成図、横断的なデータフロー | Mermaid | `docs/architecture/system-overview.md` |
| プロジェクト全体のコーディング規約の詳細 | Markdown | `docs/conventions.md` |
| ドメイン用語集 | Markdown(表形式) | `docs/domain-glossary.md` |
| AWS / K8s リソースの一覧 | YAML | `docs/references/resources.yaml` |
| 既存の Visio / draw.io 図 | 画像 + テキスト説明 | `docs/diagrams/*.png` |

これらのファイルは `config.yaml` の `context` から **参照先として明示** することで、
AI が変更内容に応じて読みに行きます。

---

## 2. `openspec/specs/<capability>/spec.md`

各 capability の **現状の振る舞い** を記述する場所です。データフロー、
処理シーケンス、コンポーネント関係など、その機能に関わるすべての情報を含めます。

spec.md の詳細なテンプレートは `feature-spec-template.md` を参照してください
(EARS 形式、Scenario、Rationale、NFR の記法を含む)。

### capability の単位

capability(機能領域)の単位を **適切に小さく保つ** ことが、spec.md の品質を
維持するコツです。目安:

- 1 つの spec.md が 1 つの明確な責務を持つ
- データフローを Mermaid 図 1 枚で表現できる粒度
- 変更時に関連する Requirement が 5〜15 個程度

capability が大きすぎると、spec.md が肥大化して AI の理解が散漫になり、
小さすぎると capability 間の依存関係が複雑になります。

### spec.md に書く内容

- frontmatter(識別情報、関係性)
- 目的(その capability が存在する理由)
- スコープ(対象範囲と対象外)
- 機能要件(EARS 形式の Requirement と Scenario)
- 非機能要件(性能、信頼性など)
- インターフェース(外部システムとの I/O)
- データモデル(永続化するデータがある場合)
- 制約事項、前提条件、依存関係
- データフロー図(Mermaid で記述)
- 参考資料(関連 ADR、Issue)

データフローや状態遷移は、spec.md 内に Mermaid で直接記述します。
capability の単位を適切に保つことで、外部ファイルへの分離は通常不要です。

---

## 3. プロンプトテンプレート

`/opsx-propose` を実行する際のプロンプトです。状況に応じて 5 つのパターンを
使い分けます。

### パターン A:新規機能追加

```markdown
/opsx-propose <change-name>

## 目的
<この機能で何を達成したいか、2〜4 文で記述>

## 背景
<なぜ今これが必要か。過去の障害、ビジネス要件、技術的負債など>

## 影響を受ける Capability
<新規 capability の場合: 「新規 capability として <new-capability-id> を作成」>
<既存 capability に影響する場合: 「<existing-capability-id> を modified」>

## 既存資産との関係
- <この機能が依存する既存の capability、ライブラリ、サービス>
- <この機能を呼び出す予定の既存処理>

## 重要な制約
- <絶対に守るべき制約>
- <避けるべき技術選択肢>

## 想定シナリオ(概要)
- 正常系: <一行で>
- 異常系: <一行で>

## 関連情報
- 関連 Issue / PR: <あれば>
- 参考 ADR: <あれば>
- 参考実装: <あれば>
```

### パターン B:既存機能の修正(該当 capability の spec が未起こし)

```markdown
/opsx-propose <change-name>

## 目的
<変更で何を達成したいか、2〜4 文で記述>

## 重要な注意:OpenSpec 導入直後
対象 capability <capability-id> の spec はまだ openspec/specs/ に存在しません。

したがって以下の順序で進めてください:

1. 既存実装(下記の関連ファイル)を精読し、現状の挙動を整理する
2. <capability-id> の新規 spec.md を作成し、現状の挙動を
   ADDED Requirements として記述する
3. その上で、本変更を MODIFIED Requirements として追加する

## 対象 Capability
<capability-id>

## 関連する既存実装
- <ファイルパス1>
- <ファイルパス2>
- <ファイルパス3>

## 変更内容
<何をどう変えたいか、具体的に>

## 背景
<なぜこの変更が必要か。過去の障害、運用課題など>

## 重要な制約
- <絶対に守るべき制約>

## 期待する変更後の挙動
- <変更後にこうなってほしい、という挙動>
- <現状との差分が明確になるように記述>

## 関連情報
- 関連 Issue / PR: <あれば>
- 参考 ADR: <あれば>
```

### パターン C:既存機能の修正(該当 capability の spec が既に存在)

```markdown
/opsx-propose <change-name>

## 目的
<変更で何を達成したいか、2〜4 文で記述>

## 対象 Capability
<capability-id>
(openspec/specs/<capability-id>/spec.md に既存仕様あり)

## 変更内容
<何をどう変えたいか、具体的に>

## 背景
<なぜこの変更が必要か>

## 重要な制約
- <絶対に守るべき制約>

## 期待する変更後の挙動
- <変更後にこうなってほしい、という挙動>

## 関連情報
- 関連 Issue / PR: <あれば>
```

### パターン D:バグ修正

```markdown
/opsx-propose <change-name>

## 目的
バグ修正: <バグの概要>

## バグの内容
<何が問題か、再現手順>

## 期待される正しい挙動
<本来こう動くべき、という記述>

## 影響を受ける Capability
<capability-id>

<該当 capability の spec が存在しない場合は、パターン B の
「OpenSpec 導入直後」セクションを追加>

## 関連する既存実装
- <ファイルパス1>
- <ファイルパス2>

## 関連情報
- バグ報告: <Issue 番号など>
- 発生環境: <prod / staging / dev>
- 影響範囲: <影響を受けるユーザー、システム範囲>
```

### パターン E:既存機能の spec 化のみ(変更を伴わない)

```markdown
/opsx-propose document-<capability-id>

## 目的
<capability-id> の現状仕様を openspec/specs/ に永続化する。
実装に変更はなく、AI が今後参照できる状態を作ることが目的。

## 対象 Capability
<capability-id>

## 関連する既存実装
- <ファイルパス1>
- <ファイルパス2>

## 指示
1. 上記の既存実装を精読する
2. 現状の挙動を ADDED Requirements として整理する
3. データフローや処理シーケンスがあれば spec.md 内に Mermaid で記述する
4. tasks.md は「ドキュメント作成のみ、実装変更なし」と明記する
5. design.md は既存実装の概要を簡潔に記述する

## 既知の制約や前提
<実装上の暗黙の前提があれば記述>

## 関連情報
- 関連 ADR: <あれば>
- 過去の障害報告: <あれば>
```

### パターンの使い分け

| 状況 | 使用パターン |
|---|---|
| 全く新しい機能を追加 | A |
| 既存機能を変更したいが spec がない | B |
| 既存機能を変更、spec は存在 | C |
| バグ修正 | D(該当部分は B または C のルールに従う) |
| 既存機能を spec 化するだけ | E |

---

## 運用フロー

### フェーズ 1:初期セットアップ

1. `openspec init` で OpenSpec を初期化(`--tools` で使用する AI ツールを指定)
2. `config.yaml` を上記テンプレートで作成
3. 必要なら `docs/architecture/system-overview.md` などの補助ファイルを最小限作成
4. プロンプトテンプレートを手元に保存

補助ファイルは最初から完璧を目指さず、運用しながら追記します。

### フェーズ 2:最初の 1 機能で「お手本」を作る

1. 一番シンプルで影響範囲の小さい既存機能を 1 つ選ぶ
2. パターン E(spec 化のみ)で `/opsx-propose` を実行
3. 生成された spec をレビュー、必要に応じて手動修正
4. `/opsx-apply` → `/opsx-archive` で `openspec/specs/<capability>/spec.md` に永続化

この最初の spec が、以降の `/opsx-propose` で AI が参照する「お手本」になります。
時間をかけて品質を整える価値があります。

### フェーズ 3:検証サイクル

各機能で次のループを回します:

1. 適切なパターンを選んで `/opsx-propose` 実行
2. 生成された artifact をレビュー
3. 不満な点があれば、原因に応じた場所に昇格:

| 不満の種類 | 昇格先 |
|---|---|
| 構造的な問題(EARS 形式が崩れる、Rationale がない) | `openspec/config.yaml` の `rules.specs` |
| 出力言語、表記ルールのブレ | `openspec/config.yaml` の `context` |
| プロジェクト全体の前提が抜けている | `openspec/config.yaml` の `context` または `docs/` 配下 |
| その capability の振る舞いの認識ズレ | 該当 `openspec/specs/<capability>/spec.md` |
| その機能固有の情報が伝わっていない | プロンプトテンプレート |

4. 修正を反映した状態で、次の機能で再度試行

### フェーズ 4:定常運用

機能 5〜10 個目以降になると:

- `config.yaml` がほぼ安定
- プロンプトは目的・対象 Capability・変更内容程度の最小構成で済む
- AI の出力品質が高く、レビューでの修正がほぼ不要に

---

## OpenSpec の基本ワークフロー

`/opsx-propose` 実行後の流れ:

```
1. /opsx-propose <change-name>  変更を提案、計画 artifact を一括生成
   ↓
   (生成された artifact をレビュー、必要なら修正)
   ↓
2. /opsx-apply                  tasks.md に従って実装
   ↓
3. /opsx-archive                完了した change を specs/ にマージ
```

各ステップでファイルを直接編集できる柔軟性があり、提案 → 実装 → アーカイブの
順序を厳格に守る必要はありません。気付きがあればどの段階でも前の artifact に
戻って修正できます。

---

## 評価指標

ブラッシュアップが進んだかの判断材料:

| 指標 | 初期 | 定常運用後 |
|---|---|---|
| プロンプトの長さ | 50〜100 行 | 10〜20 行 |
| 生成された spec の手動修正箇所 | 5〜10 箇所 | 0〜2 箇所 |
| `/opsx-propose` から `/opsx-archive` までの所要時間 | 数時間 | 1 時間以内 |
| EARS 形式の準拠率 | 50〜70% | 95% 以上 |
| Rationale の自動付与 | 0〜30% | 80% 以上 |
| 数値を含む NFR の生成 | 0〜50% | 90% 以上 |

---

## トラブルシューティング

### Q1:生成された spec が config.yaml の指示に従わない

1. `config.yaml` の `rules.specs` の項目が抽象的すぎないか確認する
   - 悪い例: 「適切に書く」
   - 良い例: 「各 Requirement に Scenario を 1 つ以上含める」
2. 矛盾する指示がないか確認する
3. それでも改善しない場合、その指示を `context` フィールドに移動する

### Q2:プロンプトを充実させても出力品質が上がらない

1. プロンプトに書いた情報が `config.yaml` の `context` と重複していないか確認する
2. プロンプトが長すぎないか確認する(300 行を超えると AI の注意が散漫になる)
3. 「AI が知らないと判断できない情報」だけに絞れているか確認する
4. 「お手本」となる既存 spec があるか確認する

### Q3:既存実装を読まずに想像で spec を書く

1. プロンプトに「既存実装を **精読してから** 作成してください」と明示する
2. 関連ファイルのパスをプロンプトに具体的に列挙する
3. AI ツールがファイル読み込み機能を持っているか確認する
4. それでも不十分なら、一度 `/opsx-explore` で調査を依頼してから `/opsx-propose` に進む

### Q4:生成された spec に他機能の話が混ざる

これは capability の境界が AI に伝わっていないサインです。

1. プロンプトの「対象 Capability」を明示する
2. 既存の spec.md がある場合、frontmatter の `depends_on` / `consumed_by` で
   関係性を明示する
3. `/opsx-explore` で「この変更が影響する capability の範囲」を先に確認してから
   `/opsx-propose` に進む

### Q5:同じ修正を毎回手動でしている

修正の種類に応じて昇格します:

| 修正の種類 | 昇格先 |
|---|---|
| 構造的な修正 | `openspec/config.yaml` の `rules.specs` |
| プロジェクト全体の前提 | `openspec/config.yaml` の `context` |
| 表記ルール、言語 | `openspec/config.yaml` の `context` |
| 特定 capability の振る舞いの認識ミス | 該当 `openspec/specs/<capability>/spec.md` |

### Q6:`context` が 50KB の上限に近づいた

`context` には 50KB(UTF-8 バイト数)の上限があります。日本語で約 16,000 文字が目安です。

1. 詳細な情報は `docs/` 配下の補助ファイルに切り出す
2. `context` には参照先を明示するだけにする
3. 例: 「コーディング規約の詳細は `docs/conventions.md` を参照」

---

## まとめ

OpenSpec 1.0+ でのスターターキットは次の構成です:

| ファイル | 役割 |
|---|---|
| `openspec/config.yaml` | プロジェクト全体の規約と AI への指示(毎回自動注入) |
| `openspec/specs/<capability>/spec.md` | 個別 capability の現状仕様(運用しながら蓄積) |
| `feature-spec-template.md` | spec.md を書く際の詳細テンプレート |
| プロンプトテンプレート | 機能ごとの可変情報 |
| `docs/` 配下の補助ファイル | 詳細な規約、構成図、ドメイン用語(必要に応じて) |

**最も重要な原則**:

- プロジェクト全体の話だけが `openspec/config.yaml` に入る
- 個別機能の話はすべて該当 `openspec/specs/<capability>/spec.md` に入る
- 両者を混同しない

これを守ることで、AI が誤った文脈で判断することを防ぎます。

---

## 公式情報の出典

このスターターキットは以下の公式情報に基づいています:

- [OpenSpec - Getting Started](https://github.com/Fission-AI/OpenSpec/blob/main/docs/getting-started.md)
- [OpenSpec - Customization](https://github.com/Fission-AI/OpenSpec/blob/main/docs/customization.md)
- [OpenSpec - Commands](https://github.com/Fission-AI/OpenSpec/blob/main/docs/commands.md)
- [OpenSpec - Concepts](https://github.com/Fission-AI/OpenSpec/blob/main/docs/concepts.md)
- [OpenSpec - Migration Guide](https://github.com/Fission-AI/OpenSpec/blob/main/docs/migration-guide.md)
- [OpenSpec 1.0 Release Notes](https://github.com/Fission-AI/OpenSpec/releases/tag/v1.0.0)
