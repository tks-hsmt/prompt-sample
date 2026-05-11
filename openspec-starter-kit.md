# OpenSpec 運用スターターキット

OpenSpec を導入したプロジェクトで、AI が常に参照する仕様を整備するための完成系セットです。
3 つのファイル(`project.md`、`config.yaml`、プロンプトテンプレート)を組み合わせて運用します。

## 全体像

```
┌──────────────────────────────────────────────────────────────────┐
│                    各ファイルの役割と関係                          │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  openspec/project.md     プロジェクト全体の不変的な文脈           │
│  ├─ 役割: 「Kubernetes 上の Fluentd」など、毎回の前提情報         │
│  └─ 効果: すべての /opsx-propose に自動的に注入される             │
│                                                                  │
│  openspec/config.yaml    spec 生成の構造的ルール                  │
│  ├─ 役割: テンプレート構造、EARS、modal verb の使い分け          │
│  └─ 効果: 出力される spec の構造を一貫させる                      │
│                                                                  │
│  プロンプトテンプレート   機能ごとの可変情報                       │
│  ├─ 役割: その機能特有の目的、背景、制約                          │
│  └─ 効果: AI に業務的な判断材料を渡す                             │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 1. `openspec/project.md`(プロジェクト全体の文脈)

このファイルの内容は **すべての /opsx-propose 実行時に AI に注入** されます。
書きすぎると逆に AI の注意が散漫になるので、「機能ごとには変わらないが、AI が知らないと正しい
判断ができない情報」だけを書きます。

### 完成系テンプレート

```markdown
# Project Overview

このプロジェクトに関する基本情報。すべての OpenSpec ワークフローで参照される。

## プロジェクトの目的

<1〜3 文でプロジェクト全体の目的を書く>

例:
Kubernetes (EKS) 上で動作する syslog 処理パイプライン。
複数の AWS アカウントからの syslog を集約し、フィルタリング・タグ付け後、
ダウンストリームの HTTP エンドポイントおよび SQS に転送する。

## 技術スタック

<使用している主要技術とバージョンを列挙する>

例:
- **オーケストレーション**: Kubernetes (Amazon EKS 1.32)
- **ログ収集**: rsyslog (DaemonSet)
- **ログ処理**: Fluentd (DaemonSet、Ruby ベース、カスタムフィルタプラグイン含む)
- **配布**: Helm 3.x、ECR (イメージ管理)、S3 (ルール配布)
- **CI/CD**: AWS CodePipeline、CodeBuild
- **IaC**: Terraform 1.x、Helm chart
- **AWS サービス**: S3、SQS、IAM (Pod Identity)、Lambda、ALB

## アーキテクチャ概要

<システム全体のデータフローを記述する>

例:
データフロー:

syslog (外部) → rsyslog (DaemonSet)
              → Fluentd (DaemonSet、フィルタプラグイン適用)
              → HTTP downstream または SQS

主要コンポーネントの責務:
- rsyslog: syslog 受信、Fluentd へのフォワード
- Fluentd: タグルーティング、レコード変換、エンリッチメント
- Fluentd プラグイン (Ruby):
  - filter_rule_match: CSV ベースのルールマッチング
  - timestamp_normalize: タイムスタンプ正規化
  - utf8_encode: 文字エンコーディング正規化
  - rule_match: パターンマッチング
  - restore_pri: syslog priority 復元

## コーディング規約

<このプロジェクトで遵守すべきコーディング規約>

例:
### Ruby (Fluentd プラグイン)
- bundler、rake、test-unit を使用
- 単体テストは Docker イメージ内で実行(外部 gem アクセスなし)
- ログ出力は構造化形式(JSON)で `$log` を使用

### Helm chart
- values.yaml に環境別の設定を分離
- values.schema.json で必ずバリデーション
- ConfigMap で外部設定を注入(コードにハードコードしない)

### Terraform
- modules/ 配下で再利用可能なリソースを定義
- リソース命名規則: `<env>-<service>-<resource>`(例: prod-fluentd-sa)
- 外部管理リソースは data ソースで参照

## 不変の原則 (Constitution)

<このプロジェクトで絶対に守るべき原則>

例:
- 設定はコードと分離する(in-memory ハードコード禁止)
- すべての配布リソース(ルール、設定)は S3 を介する
- Pod Identity を使用する(IRSA は使わない)
- 障害発生時、メインパイプラインは MUST NOT 停止する
- ログは構造化形式 (JSON) で出力する
- カバレッジは単体テストで 80% 以上を維持する

## 既存 Capability(順次 spec 化される)

<OpenSpec で管理する予定の機能の一覧。spec 化が完了したら status を更新>

| Capability ID | 状態 | 説明 |
|---|---|---|
| csv-rule-distribution | 未起こし | S3 からの分類ルール配布 |
| fluentd-tag-routing | 未起こし | タグベースのルーティング |
| buffer-management | 未起こし | Fluentd のバッファ管理 |
| timestamp-normalization | 未起こし | タイムスタンプ正規化 |
| utf8-encoding | 未起こし | 文字エンコーディング正規化 |

(spec 化完了後は「spec 化済み」に更新する)

## 用語集

<プロジェクト固有の用語の定義。業界共通用語は書かない>

| 用語 | 定義 |
|---|---|
| ルールテーブル | メモリ上に保持される {pattern, action} のマップ |
| 配布元 CSV | S3 上の `s3://<bucket>/rules.csv` |
| Pod Identity | EKS の IAM ロール委譲機構(EKS Pod Identity Agent 経由) |

## 参考リンク

- 内部設計ドキュメント: <Confluence などへのリンク>
- ADR (Architecture Decision Records): `docs/adr/`
- 過去の障害報告書: <wiki などへのリンク>
```

### project.md 作成時のコツ

- **書きすぎない**:5〜10 個の主要技術と、簡潔なアーキテクチャ説明で十分。詳細は spec で書く
- **書かないでよいもの**:タスクの進め方、コミットメッセージのルール(これらは AGENTS.md 側)
- **更新タイミング**:大きな技術変更があったとき(主要バージョン更新、新サービス導入時)
- **既存 Capability の表**:spec 化の進捗を可視化することで、AI も Takeshi さん自身も現状を把握できる

---

## 2. `openspec/config.yaml`(spec 生成の構造的ルール)

このファイルは **生成される spec の構造を一貫させる** ために使います。
`context` フィールドは AI に毎回注入され、`rules` フィールドは artifact 種別ごとの追加制約を指定します。

### 完成系テンプレート

```yaml
schema: spec-driven

context: |
  # 言語と表記ルール

  Language: Japanese

  すべての成果物(proposal.md、spec.md、design.md、tasks.md)は日本語で
  作成してください。ただし以下は英語のままにしてください:

  - "### Requirement:" "#### Scenario:" のセクション見出し
  - GIVEN / WHEN / THEN / AND(BDD のキーワード)
  - SHALL / MUST / SHOULD / MAY / MUST NOT(RFC 2119 の規範語)
  - When / While / If / Where / Otherwise(EARS のパターン識別子)

  技術用語(Kubernetes、Helm、Fluentd、Pod、Service、Capability など)も
  英語のまま使用してください。

  # 共通の前提

  - すべての requirement は測定可能・検証可能な形式で記述する
  - 数値が必要な箇所では具体的な値を含める(「速い」「使いやすい」は不可)
  - 既存実装と矛盾する spec を作らない(矛盾する場合は MODIFIED で明示)
  - 既存の openspec/specs/ 配下の spec を参考にして、同じスタイルで生成する

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
    - 機能要件は EARS 形式で書く(Ubiquitous、Event-Driven、State-Driven、Optional、Unwanted Behavior)
    - SHALL / MUST / SHOULD / MAY を RFC 2119 に従って使い分ける
    - 各 Requirement には Scenario を 1 つ以上含める
    - 複雑な要件には #### Rationale セクションで根拠を書く
    - 非機能要件は性能、信頼性、セキュリティ、観測性、保守性のカテゴリで分類する
    - すべての非機能要件には測定可能な数値を含める
    - 外部システムとの I/O がある場合は "## インターフェース" セクションを書く
    - "## 制約事項" には理由も併記する
    - "## 対象外" には「やらないこと」とその理由を書く

  design:
    - 採用した技術の選定理由を必ず明記する
    - 代替案を 1 つ以上検討し、なぜそれを採用しなかったかを書く
    - 既存アーキテクチャとの整合性を確認するセクションを含める
    - 障害シナリオと対処方法を含める
    - 監視・運用観点を含める(メトリクス、アラート、ログ)
    - 複雑な処理フローにはシーケンス図を含める(Mermaid 形式)

  tasks:
    - 各タスクは独立に実装・テスト可能な単位に分割する
    - タスクには依存関係がある場合、依存元タスクの番号を明記する
    - 単体テスト、統合テストの作成タスクを必ず含める
    - 本番反映前の検証手順をタスクとして含める
    - 影響の大きい変更(IAM、本番設定など)は実装前にユーザー確認を求めるよう明記する
```

### config.yaml 作成時のコツ

- **`context` は技術非依存の指示**:言語、表記ルール、品質基準など
- **`rules` は artifact 種別ごとの指示**:proposal は影響範囲、spec は構造、design は技術判断、tasks は分割粒度
- **検証フェーズで育てる**:最初は最小構成で開始し、AI の出力をレビューして「毎回修正している項目」を rules に追加する
- **冗長な指示は避ける**:同じことを複数箇所に書かない(優先順位が AI に伝わりにくくなる)

---

## 3. プロンプトテンプレート(機能ごとの可変情報)

`/opsx-propose` を実行する際のプロンプトの完成系です。
新規機能追加、既存機能修正、バグ修正で微妙にフォーマットが異なります。

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
このプロジェクトは OpenSpec を導入したばかりで、対象 capability
<capability-id> の spec はまだ openspec/specs/ に存在しません。

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
- <避けるべき技術選択肢>

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
- <ファイルパス3>

## 指示
1. 上記の既存実装を精読する
2. 現状の挙動を ADDED Requirements として整理する
3. 既存実装のテストファイル(<テストファイルパス>)も参考にする
4. tasks.md は「ドキュメント作成のみ、実装変更なし」と明記する
5. design.md は既存実装の概要を簡潔に記述する

## 既知の制約や前提
<実装上の暗黙の前提があれば記述>

## 関連情報
- 関連 ADR: <あれば>
- 過去の障害報告: <あれば>
```

---

## プロンプトテンプレートの使い分け早見表

| 状況 | 該当パターン | 該当 spec の有無 |
|---|---|---|
| 全く新しい機能を追加 | A | 該当なし |
| 既存機能を変更したいが spec がない | B | なし |
| 既存機能を変更、spec は存在 | C | あり |
| バグ修正(spec の有無問わず) | D | 該当部分は B または C のルールに従う |
| 既存機能を spec 化するだけ | E | なし(これから作る) |

---

## 運用フロー(ブラッシュアップの進め方)

最初の数機能では「config の充実」と「プロンプトの最適化」を並行して進めます。

### フェーズ 1:初期セットアップ(1 日程度)

1. `project.md` を上記テンプレートで作成
2. `config.yaml` を上記テンプレートで作成
3. プロンプトテンプレートを手元に保存(VS Code Snippets 等に登録すると便利)

### フェーズ 2:最初の 1 機能で「お手本」を作る(数時間)

1. 一番シンプルで影響範囲の小さい既存機能を 1 つ選ぶ
2. パターン E(spec 化のみ)で `/opsx-propose` を実行
3. 生成された spec をレビュー、必要に応じて手動修正
4. `/opsx-apply` → `/opsx-archive` で永続化
5. 完成した `openspec/specs/<capability>/spec.md` を Takeshi さんが満足する品質に整える

これが今後の AI の参考データになります。最初は時間をかけて整える価値があります。

### フェーズ 3:検証サイクル(3〜5 機能、数日〜1 週間)

各機能で次のループを回します:

1. 適切なパターンを選んで `/opsx-propose` 実行
2. 生成された artifact をレビュー
3. 不満な点があれば、原因を切り分け:
   - **構造的な問題(EARS 形式が崩れている、Rationale がない等)**:
     → `config.yaml` の `rules.specs` に追加
   - **プロジェクト固有の前提が抜けている**:
     → `project.md` に追加
   - **その機能固有の情報が伝わっていない**:
     → プロンプトテンプレートを充実
4. 修正を反映した状態で、次の機能で再度試行

### フェーズ 4:定常運用(機能 5〜10 個目以降)

- `project.md` と `config.yaml` がほぼ安定
- プロンプトは「目的」「対象 Capability」「変更内容」程度の最小構成で済むようになる
- AI の出力品質が高く、レビューでの修正がほぼ不要に

---

## 評価指標(ブラッシュアップが進んだかの判断材料)

以下が改善していれば、ブラッシュアップが進んでいるサインです:

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

### Q1:生成された spec が config.yaml の指示に従っていない

**対処**:

1. `config.yaml` の `rules.specs` に書いた項目が、抽象的すぎないか確認
   - 悪い例: "適切に書く"
   - 良い例: "各 Requirement に Scenario を 1 つ以上含める"
2. 矛盾する指示がないか確認(複数箇所で違うことを言っていないか)
3. それでも改善しない場合、その指示を `context` フィールドに移動する
   (context の方が優先度が高いと AI が認識する傾向がある)

### Q2:プロンプトを充実させても AI の出力品質が上がらない

**対処**:

1. プロンプトに書いた情報が `project.md` と重複していないか確認
2. プロンプトが長すぎないか確認(300 行を超えると AI の注意が散漫になる)
3. 「AI が知らないと判断できない情報」だけに絞れているか確認
   - 「これは AI でも常識的に分かるだろう」と思える情報は削除
4. 「お手本」となる既存 spec があるか確認
   (`openspec/specs/` に 1 つでも完成度の高い spec があれば、AI はそれを真似る)

### Q3:既存実装を読まずに想像で spec を書く

**対処**:

1. プロンプトに「上記の既存実装を **精読してから** 作成してください」と明示
2. 関連ファイルのパスをプロンプトに具体的に列挙する
3. AI ツールがファイル読み込み機能を持っているか確認(Copilot Chat は `@workspace`、Claude Code は自動)
4. それでも不十分なら、一度 `/opsx-explore` で既存実装の調査を依頼してから `/opsx-propose` に進む

### Q4:同じ修正を毎回手動でしている

**対処**:

これは config.yaml に昇格すべきサインです。次のいずれかに追加します:

- 構造的な修正 → `rules.specs` または `rules.proposal` 等
- プロジェクト固有の前提 → `project.md`
- 表記ルール → `context`

---

## まとめ

OpenSpec 導入時のスターターキットは以下の 3 点セットです:

1. **`openspec/project.md`**:プロジェクト全体の不変的な文脈(技術スタック、原則、用語)
2. **`openspec/config.yaml`**:spec 生成の構造的ルール(言語、EARS、各 artifact の要件)
3. **プロンプトテンプレート**:機能ごとの可変情報(目的、背景、影響範囲)

これら 3 つを最初に整え、運用しながらブラッシュアップしていくことで、Takeshi さんの当初の目的
「○○の機能は□□という仕様である」を AI が常に参照する状態が、段階的に実現されます。

最初は手作業が多く感じるかもしれませんが、5〜10 機能を経るころには `project.md` と
`config.yaml` がほぼ安定し、プロンプトも最小限で済むようになります。
最初の 1〜2 機能だけは時間をかけて「お手本」となる品質に整える価値があります。
