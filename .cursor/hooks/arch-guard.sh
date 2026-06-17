#!/bin/bash
# Architecture guard hook wrapper (calls scripts/arch-guard.sh)
set -euo pipefail

input=$(cat)
FILE=$(echo "$input" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('file_path','') or d.get('path','') or '')" 2>/dev/null || true)

[ -z "$FILE" ] && exit 0

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
bash "$ROOT/scripts/arch-guard.sh" "$FILE"
exit 0
