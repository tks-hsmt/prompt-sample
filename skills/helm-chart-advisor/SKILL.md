---
name: helm-chart-advisor
description: |
  Helm chart の作成・編集・レビューを、ベストプラクティスに基づいて行うスキル。
  ユーザーが Helm chart を新規作成したい、既存の Helm chart を修正したい、Helm chart のレビューやセキュリティチェックをしたい、
  values.yaml の設計やテンプレートの構造について相談したい、といった場合に使用する。
  Kubernetes デプロイ、Helm、k8s マニフェスト、Chart.yaml、values.yaml、helm install/upgrade に関する作業全般でトリガーすること。
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash(helm lint*)
  - Bash(helm template*)
  - Bash(helm create*)
  - Bash(helm install --dry-run*)
  - Bash(helm dependency*)
  - Bash(helm show*)
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

## リファレンス一覧

`references/` 配下にトピック別のベストプラクティスを格納している。

| ファイル | 内容 |
|---|---|
| `confirmation-rules.md` | 構成・変更内容の確認ルール（挙動説明、不整合チェック）— 全モード共通 |
| `chart-structure.md` | チャート命名規則、SemVer 2 バージョニング、スキャフォールド |
| `values.md` | values.yaml 設計、命名規則、スキーマ検証 |
| `templates.md` | テンプレート構造、フォーマット、コメント |
| `dependencies.md` | 依存チャート管理、CRD |
| `security.md` | securityContext、NetworkPolicy、ServiceAccount |
| `workloads.md` | コンテナイメージ、リソース、プローブ、ラベル |
| `operations.md` | helm upgrade/install フラグ、CI/CD、テスト、シークレット |
| `ecosystem.md` | OCI レジストリ、Helmfile、ArgoCD、ドキュメント、Helm 4 |

## 出力テンプレート

`assets/` 配下にプラン・レビュー結果の出力テンプレートを格納している。各モードの手順で出力ファイルを作成する際に参照する。

| ファイル | 用途 |
|---|---|
| `create-plan-template.md` | 新規作成プランの出力テンプレート |
| `edit-plan-template.md` | 編集プランの出力テンプレート |
| `review-result-template.md` | レビュー結果の出力テンプレート |
