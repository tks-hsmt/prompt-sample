#!/usr/bin/env bash
# copy-template.sh — ワークロードテンプレートをコピーし CHARTNAME を置換する
#
# Usage: bash copy-template.sh <workload> <output-dir> <chart-name>
#
# 引数:
#   workload    : deployment | daemonset | statefulset | job | cronjob
#   output-dir  : チャートを作成する親ディレクトリ
#   chart-name  : 作成するチャート名（小文字英数+ハイフン）
#
# 動作:
#   1. templates/<workload>/ から <output-dir>/<chart-name>/ へ全ファイルコピー
#   2. 全ファイル内の CHARTNAME プレースホルダーを <chart-name> に置換
#   3. 結果をユーザーに表示

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"

# 引数チェック
if [ "$#" -ne 3 ]; then
    echo "Usage: bash $0 <workload> <output-dir> <chart-name>" >&2
    echo "  workload    : deployment | daemonset | statefulset | job | cronjob" >&2
    echo "  output-dir  : チャートを作成する親ディレクトリ" >&2
    echo "  chart-name  : 作成するチャート名（小文字英数+ハイフン）" >&2
    exit 1
fi

WORKLOAD="$1"
OUTPUT_DIR="$2"
CHART_NAME="$3"

# ワークロード種別の検証
case "$WORKLOAD" in
    deployment|daemonset|statefulset|job|cronjob)
        ;;
    *)
        echo "Error: 不正なワークロード種別: $WORKLOAD" >&2
        echo "  使用可能: deployment | daemonset | statefulset | job | cronjob" >&2
        exit 2
        ;;
esac

# チャート名の検証（小文字英数+ハイフンのみ、先頭は英字）
if ! [[ "$CHART_NAME" =~ ^[a-z][a-z0-9-]*$ ]]; then
    echo "Error: チャート名は小文字英字で始まり、小文字英数とハイフンのみ使用可能: $CHART_NAME" >&2
    exit 3
fi

# テンプレートディレクトリの存在チェック
TEMPLATE_DIR="$SKILL_DIR/templates/$WORKLOAD"
if [ ! -d "$TEMPLATE_DIR" ]; then
    echo "Error: テンプレートディレクトリが見つかりません: $TEMPLATE_DIR" >&2
    exit 4
fi

# 出力ディレクトリの作成
TARGET_DIR="$OUTPUT_DIR/$CHART_NAME"
if [ -d "$TARGET_DIR" ]; then
    echo "Error: 出力先ディレクトリが既に存在します: $TARGET_DIR" >&2
    echo "  別のディレクトリを指定するか、既存ディレクトリを削除してください。" >&2
    exit 5
fi

mkdir -p "$OUTPUT_DIR"

# テンプレートコピー
echo "[1/3] テンプレートをコピー中: $TEMPLATE_DIR -> $TARGET_DIR"
cp -r "$TEMPLATE_DIR" "$TARGET_DIR"

# CHARTNAME 置換
echo "[2/3] CHARTNAME を $CHART_NAME に置換中..."
REPLACED_FILES=0
while IFS= read -r -d '' file; do
    if grep -q 'CHARTNAME' "$file"; then
        # macOS と Linux 両対応の sed
        if [[ "$(uname)" == "Darwin" ]]; then
            sed -i '' "s/CHARTNAME/$CHART_NAME/g" "$file"
        else
            sed -i "s/CHARTNAME/$CHART_NAME/g" "$file"
        fi
        REPLACED_FILES=$((REPLACED_FILES + 1))
    fi
done < <(find "$TARGET_DIR" -type f \( -name '*.yaml' -o -name '*.tpl' -o -name '*.txt' -o -name '*.gotmpl' -o -name '*.json' \) -print0)

echo "  $REPLACED_FILES ファイルで置換を実施"

# 残存チェック
echo "[3/3] CHARTNAME 残存チェック..."
REMAINING=$(grep -r 'CHARTNAME' "$TARGET_DIR" 2>/dev/null || true)
if [ -n "$REMAINING" ]; then
    echo "Warning: 以下のファイルに CHARTNAME が残存しています:" >&2
    echo "$REMAINING" >&2
    exit 6
fi

# 結果サマリ
echo ""
echo "✓ テンプレートコピー完了"
echo ""
echo "  ワークロード: $WORKLOAD"
echo "  チャート名:   $CHART_NAME"
echo "  作成場所:     $TARGET_DIR"
echo ""
echo "  作成されたファイル:"
find "$TARGET_DIR" -type f | sed "s|$TARGET_DIR/|    |"
echo ""
echo "次のステップ:"
echo "  1. $TARGET_DIR/values.yaml を計画ファイルに従って編集"
echo "  2. $TARGET_DIR/Chart.yaml の description と appVersion を更新"
echo "  3. bash $SCRIPT_DIR/validate-chart.sh $TARGET_DIR で検証"
