#!/usr/bin/env bash
# AI-DLC workflowsのルールをGitLabプロジェクトに統合するスクリプト
#
# 使用法:
#   ./scripts/setup-aidlc.sh
#
# 実行後、aidlc-rules/ をGitLabにpushすることで
# construction_agent.py が自動的にルールを読み込みます。

set -euo pipefail

AIDLC_REPO="https://github.com/awslabs/aidlc-workflows.git"
TEMP_DIR=$(mktemp -d)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cleanup() {
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

echo "=== AI-DLC workflows をダウンロード ==="
git clone --depth 1 "$AIDLC_REPO" "$TEMP_DIR/aidlc-workflows"

echo "=== ルールをプロジェクトにコピー ==="
mkdir -p "$PROJECT_ROOT/aidlc-rules"
cp -r "$TEMP_DIR/aidlc-workflows/aidlc-rules/"* "$PROJECT_ROOT/aidlc-rules/"

# Claude Code向け設定もコピー（任意）
if [[ -d "$TEMP_DIR/aidlc-workflows/.claude" ]]; then
  echo "=== Claude Code設定をコピー ==="
  cp -r "$TEMP_DIR/aidlc-workflows/.claude/"* "$PROJECT_ROOT/.claude/" 2>/dev/null || true
fi

echo ""
echo "=== セットアップ完了 ==="
echo ""
echo "コピーされたファイル:"
find "$PROJECT_ROOT/aidlc-rules" -type f | sed "s|$PROJECT_ROOT/||"
echo ""
echo "次のステップ:"
echo "  1. git add aidlc-rules/"
echo "  2. git commit -m 'Add AI-DLC workflow rules'"
echo "  3. git push && git push gitlab main"
echo ""
echo "pushすると construction_agent.py が自動的にルールを読み込みます。"
