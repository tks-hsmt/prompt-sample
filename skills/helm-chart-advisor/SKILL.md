---
name: helm-chart-advisor
description: |
  Helm chart の作成・編集・レビューを、ベストプラクティスに基づいて行うスキル。
  ユーザーが Helm chart を新規作成したい、既存の Helm chart を修正したい、Helm chart のレビューやセキュリティチェックをしたい、
  values.yaml の設計やテンプレートの構造について相談したい、といった場合に使用する。
  Kubernetes デプロイ、Helm、k8s マニフェスト、Chart.yaml、values.yaml、helm install/upgrade に関する作業全般でトリガーすること。
---

# Helm Chart Advisor スキル

Helm chart の作成・編集・レビューを、組織のベストプラクティスに従って行う。

## モード判定

ユーザーの依頼内容から作業モードを判定し、対応するリファレンスを読み込む。

| ユーザーの意図 | モード | 最初に読むファイル |
|---|---|---|
| 新しい Helm chart を作りたい | 新規作成 | `references/mode-create.md` |
| 既存の chart を修正・変更したい | 編集 | `references/mode-edit.md` |
| chart をレビュー・チェックしたい | レビュー | `references/mode-review.md` |

各モードのファイルに、ヒアリング項目・作業手順・追加リファレンスへのポインタが記載されている。
追加リファレンスは作業対象に関連するものだけを読み込むこと。

**プランファイルの指定**: ユーザーがプランファイル（`result/helm-chart-advisor-*-plan-*.md`）を明示的に指定した場合は、ヒアリング・構成確認をスキップし、プランファイルの内容に従って作業を行う。プランはすでにユーザーと合意済みの内容であるため、改めて確認する必要はない。

**ヒアリングと確認の原則**:
- 各モードに定義されたヒアリング項目のうち、ユーザーの依頼から読み取れない情報がある場合は、作業に着手せず先に確認する。認識が曖昧なまま進めて手戻りになるよりも、事前に確認する方がよい。回答の中で新たな不明点が出てきたら追加で確認してよい。
- ヒアリング後、作業に着手する前に構成や変更内容の確認をユーザーに提示する。指定済み・未指定を問わず全項目の挙動を明示し、パラメータ間の不整合がないかもチェックする。k8s に精通していないユーザーも想定し、専門用語だけでなく実際の影響（外部からアクセスできない、データが永続化されない等）をわかりやすく伝える。

## リファレンス一覧

`references/` 配下にトピック別のベストプラクティスを格納している。

| ファイル | 内容 |
|---|---|
| `chart-structure.md` | チャート命名規則、SemVer 2 バージョニング、スキャフォールド |
| `values.md` | values.yaml 設計、命名規則、スキーマ検証 |
| `templates.md` | テンプレート構造、フォーマット、コメント |
| `dependencies.md` | 依存チャート管理、CRD |
| `security.md` | securityContext、NetworkPolicy、ServiceAccount |
| `workloads.md` | コンテナイメージ、リソース、プローブ、ラベル |
| `operations.md` | helm upgrade/install フラグ、CI/CD、テスト、シークレット |
| `ecosystem.md` | OCI レジストリ、Helmfile、ArgoCD、ドキュメント、Helm 4 |
