#!/bin/bash
# 架构守卫和 git 钩子的本地自检. 不写仓库里的业务文件.
set -eu

root=$(git rev-parse --show-toplevel)
cd "$root"
fail=0

expect_exit() {
    local want="$1"
    shift
    set +e
    output=$("$@" 2>&1)
    code=$?
    set -e
    if [ "$code" -ne "$want" ]; then
        printf 'FAIL exit %s (want %s): %s\n%s\n' "$code" "$want" "$*" "$output"
        fail=1
        return
    fi
    printf 'ok exit %s: %s\n' "$want" "$*"
}

expect_stdout() {
    local needle="$1"
    shift
    set +e
    output=$("$@" 2>&1)
    code=$?
    set -e
    if ! printf '%s' "$output" | grep -q "$needle"; then
        printf 'FAIL missing [%s] (exit %s): %s\n%s\n' "$needle" "$code" "$*" "$output"
        fail=1
        return
    fi
    printf 'ok saw [%s]\n' "$needle"
}

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

mkdir -p "$tmp/src/backend/bisheng/common" \
    "$tmp/src/backend/bisheng/foo/api/endpoints" \
    "$tmp/src/frontend/platform/src/pages" \
    "$tmp/src/frontend/platform/src/controllers" \
    "$tmp/src/frontend/client/src/api" \
    "$tmp/src/backend/test" \
    "$tmp/src/backend/bisheng/core/database"

printf 'from bisheng.knowledge.domain.foo import Bar\n' > "$tmp/src/backend/bisheng/common/bad.py"
expect_exit 1 bash scripts/arch-guard.sh "$tmp/src/backend/bisheng/common/bad.py"
expect_stdout 'RULE-1' bash scripts/arch-guard.sh "$tmp/src/backend/bisheng/common/bad.py"

printf 'x = 1\n' > "$tmp/clean.py"
expect_exit 0 bash scripts/arch-guard.sh "$tmp/clean.py"

printf 'from bisheng.database.models.user import User\n' > "$tmp/src/backend/bisheng/foo/api/endpoints/legacy.py"
expect_exit 0 bash scripts/arch-guard.sh "$tmp/src/backend/bisheng/foo/api/endpoints/legacy.py"
expect_stdout 'RULE-3 WARNING' bash scripts/arch-guard.sh "$tmp/src/backend/bisheng/foo/api/endpoints/legacy.py"

printf 'from sqlalchemy import JSON\n' > "$tmp/json_bad.py"
expect_exit 1 bash scripts/arch-guard.sh "$tmp/json_bad.py"
expect_stdout 'RULE-9' bash scripts/arch-guard.sh "$tmp/json_bad.py"

printf '# sqlalchemy.JSON is banned\n' > "$tmp/json_comment.py"
expect_exit 0 bash scripts/arch-guard.sh "$tmp/json_comment.py"

printf 'from sqlalchemy.dialects.mysql import LONGTEXT\n' > "$tmp/src/backend/bisheng/core/database/dialect_helpers.py"
expect_exit 0 bash scripts/arch-guard.sh "$tmp/src/backend/bisheng/core/database/dialect_helpers.py"

printf 'assert "LONGTEXT" not in sql\n' > "$tmp/src/backend/test/test_dialect.py"
expect_exit 0 bash scripts/arch-guard.sh "$tmp/src/backend/test/test_dialect.py"

printf "import axios from 'axios';\n" > "$tmp/src/frontend/platform/src/pages/Bad.tsx"
expect_exit 1 bash scripts/arch-guard.sh "$tmp/src/frontend/platform/src/pages/Bad.tsx"
expect_stdout 'RULE-10' bash scripts/arch-guard.sh "$tmp/src/frontend/platform/src/pages/Bad.tsx"

printf "import axios from 'axios';\n" > "$tmp/src/frontend/platform/src/controllers/request.ts"
expect_exit 0 bash scripts/arch-guard.sh "$tmp/src/frontend/platform/src/controllers/request.ts"

printf "import axios from \"axios\";\n" > "$tmp/src/frontend/client/src/api/request.ts"
expect_exit 0 bash scripts/arch-guard.sh "$tmp/src/frontend/client/src/api/request.ts"

printf "import { Page } from 'src/frontend/client/src/pages/Page';\n" > "$tmp/src/frontend/platform/src/pages/Cross.tsx"
expect_exit 1 bash scripts/arch-guard.sh "$tmp/src/frontend/platform/src/pages/Cross.tsx"
expect_stdout 'RULE-11' bash scripts/arch-guard.sh "$tmp/src/frontend/platform/src/pages/Cross.tsx"

# 已跟踪文件里的旧 LONGTEXT 不报; 新增一行才报.
repo="$tmp/repo"
mkdir -p "$repo/pkg"
git -C "$repo" init -q
git -C "$repo" config user.email "guard@example.com"
git -C "$repo" config user.name "guard"
printf 'legacy = "LONGTEXT"\n' > "$repo/pkg/old.py"
git -C "$repo" add pkg/old.py
git -C "$repo" commit -q -m init
expect_exit 0 bash scripts/arch-guard.sh "$repo/pkg/old.py"
printf 'legacy = "LONGTEXT"\nnew = "JSON_EXTRACT"\n' > "$repo/pkg/old.py"
expect_exit 1 bash scripts/arch-guard.sh "$repo/pkg/old.py"
expect_stdout 'RULE-9' bash scripts/arch-guard.sh "$repo/pkg/old.py"

hook() {
    printf '%s' "$1" | python3 scripts/agent_hooks.py "$2"
}

expect_stdout 'RULE-9' hook "{\"tool_name\":\"Write\",\"tool_input\":{\"path\":\"$tmp/json_bad.py\"}}" cursor-post-edit
expect_stdout additionalContext hook "{\"tool_name\":\"Edit\",\"tool_input\":{\"path\":\"$tmp/json_bad.py\"}}" claude-post-edit
clean_out=$(hook "{\"tool_name\":\"Write\",\"tool_input\":{\"path\":\"$tmp/clean.py\"}}" cursor-post-edit || true)
if [ -n "$clean_out" ]; then
    printf 'FAIL clean post-edit should be silent, got: %s\n' "$clean_out"
    fail=1
else
    printf 'ok clean post-edit is silent\n'
fi

expect_stdout '"permission": "allow"' hook '{"command":"git status"}' cursor-git-safety
expect_stdout '"permission": "ask"' hook '{"command":"git checkout -b feat/x"}' cursor-git-safety
expect_stdout '"permission": "ask"' hook '{"command":"git switch -c feat/x"}' cursor-git-safety
expect_stdout '"permission": "deny"' hook '{"command":"git push --force origin HEAD"}' cursor-git-safety
expect_stdout '"permission": "deny"' hook '{"command":"git push origin -f"}' cursor-git-safety
expect_stdout '"permission": "deny"' hook '{"command":"git reset --hard HEAD"}' cursor-git-safety
expect_stdout '"permission": "deny"' hook '{"command":"git commit --no-verify -m x"}' cursor-git-safety
expect_stdout '"permission": "deny"' hook '{"command":"git status && git push --force"}' cursor-git-safety
expect_stdout '"permission": "allow"' hook '{"command":"echo git push --force"}' cursor-git-safety
expect_stdout permissionDecision hook '{"tool_name":"Bash","tool_input":{"command":"git reset --hard"}}' claude-pre-tool

python3 -c 'import json,pathlib; json.loads(pathlib.Path(".cursor/hooks.json").read_text()); json.loads(pathlib.Path(".claude/settings.json").read_text())'
printf 'ok hook json parses\n'

if [ "$fail" -ne 0 ]; then
    printf 'selftest failed\n'
    exit 1
fi
printf 'selftest passed\n'
