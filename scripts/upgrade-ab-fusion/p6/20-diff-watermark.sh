#!/usr/bin/env bash
# start vs freeze 差分. 写出 incr-created/updated/deleted.tsv
set -euo pipefail
STEP="p6.20-diff"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env

start="${LOG_DIR}/p6/start"
freeze="${LOG_DIR}/p6/freeze"
[[ -f "${start}/summary.tsv" ]] || die "缺少 ${start}/summary.tsv, 先 LABEL=start bash p6/10-capture-watermark.sh"
[[ -f "${freeze}/summary.tsv" ]] || die "缺少 ${freeze}/summary.tsv, 先 LABEL=freeze bash p6/10-capture-watermark.sh"

python3 "${PACK_ROOT}/p6/diff_watermark.py" \
  --start "${start}" \
  --freeze "${freeze}" \
  --out "${LOG_DIR}/p6"

ledger "${STEP}" "OK" ""
echo "OK ${STEP} -> ${LOG_DIR}/p6/incr-created.tsv"
