#!/usr/bin/env bash
# validate-chart.sh — Helm チャートを検証する
#
# Usage: bash validate-chart.sh <chart-dir> [--no-helm]
#
# 引数:
#   chart-dir : 検証対象のチャートディレクトリ
#   --no-helm : helm コマンドを使わず Python ベース検証のみ実行
#
# 実行する検証:
#   1. CHARTNAME 残存チェック
#   2. YAML 構文検証（全 *.yaml ファイル）
#   3. JSON Schema 検証（values.yaml が values.schema.json に準拠）
#   4. helm lint（helm が利用可能な場合）
#   5. helm template デフォルト values（helm が利用可能な場合）
#   6. helm template 各環境別 values（helm が利用可能な場合）

set -uo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: bash $0 <chart-dir> [--no-helm]" >&2
    exit 1
fi

CHART_DIR="$1"
NO_HELM=false
if [ "${2:-}" == "--no-helm" ]; then
    NO_HELM=true
fi

if [ ! -d "$CHART_DIR" ]; then
    echo "Error: チャートディレクトリが見つかりません: $CHART_DIR" >&2
    exit 2
fi

# 必須ファイルチェック
for required in "Chart.yaml" "values.yaml" "values.schema.json" "templates"; do
    if [ ! -e "$CHART_DIR/$required" ]; then
        echo "Error: 必須ファイル/ディレクトリがありません: $CHART_DIR/$required" >&2
        exit 3
    fi
done

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

pass() { echo "  ✓ $1"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail() { echo "  ✗ $1" >&2; FAIL_COUNT=$((FAIL_COUNT + 1)); }
warn() { echo "  ! $1" >&2; WARN_COUNT=$((WARN_COUNT + 1)); }

echo "==================================================="
echo "Helm チャート検証: $CHART_DIR"
echo "==================================================="

# ----------------------------------------------------
# Test 1: CHARTNAME 残存チェック
# ----------------------------------------------------
echo ""
echo "[Test 1] CHARTNAME 残存チェック"
REMAINING=$(grep -rn 'CHARTNAME' "$CHART_DIR" 2>/dev/null || true)
if [ -n "$REMAINING" ]; then
    fail "CHARTNAME プレースホルダーが残存しています:"
    echo "$REMAINING" | head -10 >&2
else
    pass "CHARTNAME プレースホルダー残存なし"
fi

# ----------------------------------------------------
# Test 2: YAML 構文検証
# ----------------------------------------------------
echo ""
echo "[Test 2] YAML 構文検証"
YAML_OK=true
while IFS= read -r -d '' yaml_file; do
    if ! python3 -c "import yaml; yaml.safe_load(open('$yaml_file'))" 2>/dev/null; then
        # テンプレートファイルは Go template を含むため安全に解析できない
        # values.yaml と Chart.yaml のみチェック
        if [[ "$yaml_file" == *"templates/"* ]]; then
            continue
        fi
        fail "YAML 構文エラー: $yaml_file"
        python3 -c "import yaml; yaml.safe_load(open('$yaml_file'))" 2>&1 | sed 's/^/    /' >&2
        YAML_OK=false
    fi
done < <(find "$CHART_DIR" -name '*.yaml' -print0)
$YAML_OK && pass "全 YAML ファイルの構文 OK"

# ----------------------------------------------------
# Test 3: JSON Schema 検証
# ----------------------------------------------------
echo ""
echo "[Test 3] JSON Schema 検証"
SCHEMA_RESULT=$(python3 << PYEOF 2>&1
import yaml, json, sys
try:
    import jsonschema
except ImportError:
    print("WARN: jsonschema ライブラリ未インストール、検証スキップ")
    sys.exit(99)

try:
    with open("$CHART_DIR/values.yaml") as f:
        values = yaml.safe_load(f)
    with open("$CHART_DIR/values.schema.json") as f:
        schema = json.load(f)
    jsonschema.validate(values, schema)
    print("OK")
except jsonschema.ValidationError as e:
    path = '.'.join(str(p) for p in e.absolute_path)
    print(f"FAIL: [{path}] {e.message}")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(2)
PYEOF
)
SCHEMA_EXIT=$?

if [ $SCHEMA_EXIT -eq 0 ]; then
    pass "JSON Schema 検証 OK"
elif [ $SCHEMA_EXIT -eq 99 ]; then
    warn "$SCHEMA_RESULT"
else
    fail "JSON Schema 検証失敗"
    echo "$SCHEMA_RESULT" | sed 's/^/    /' >&2
fi

# ----------------------------------------------------
# Test 4-7: helm lint / template (helm 利用可能時のみ)
# ----------------------------------------------------
if $NO_HELM; then
    echo ""
    echo "[Test 4-7] helm コマンド検証 — --no-helm 指定によりスキップ"
elif ! command -v helm >/dev/null 2>&1; then
    echo ""
    echo "[Test 4-7] helm コマンド検証 — helm 未インストールのためスキップ"
    warn "本番デプロイ前に必ず helm lint と helm template を実行してください"
else
    # Test 4: helm lint
    echo ""
    echo "[Test 4] helm lint"
    LINT_OUT=$(helm lint "$CHART_DIR" 2>&1)
    if [ $? -eq 0 ]; then
        pass "helm lint OK"
    else
        fail "helm lint 失敗:"
        echo "$LINT_OUT" | sed 's/^/    /' >&2
    fi
    
    # Test 5-7: helm template (各環境)
    for env in "" "dev" "stg" "prod"; do
        if [ -z "$env" ]; then
            label="デフォルト values"
            args=""
            test_num=5
        else
            label="$env 環境 values"
            values_file="$CHART_DIR/values-$env.yaml"
            if [ ! -f "$values_file" ]; then
                continue
            fi
            args="-f $values_file"
            test_num=$((test_num + 1))
        fi
        
        echo ""
        echo "[Test $test_num] helm template ($label)"
        TPL_OUT=$(helm template "$CHART_DIR" $args 2>&1)
        if [ $? -eq 0 ]; then
            pass "helm template ($label) OK"
        else
            fail "helm template ($label) 失敗:"
            echo "$TPL_OUT" | tail -20 | sed 's/^/    /' >&2
        fi
    done
fi

# ----------------------------------------------------
# 結果サマリ
# ----------------------------------------------------
echo ""
echo "==================================================="
echo "検証結果サマリ"
echo "==================================================="
echo "  成功:   $PASS_COUNT 件"
echo "  警告:   $WARN_COUNT 件"
echo "  失敗:   $FAIL_COUNT 件"
echo ""

if [ $FAIL_COUNT -gt 0 ]; then
    echo "✗ 検証失敗 — references/test-commands.md の「よくあるエラー」を参照してください"
    exit 1
fi

echo "✓ 検証成功"
