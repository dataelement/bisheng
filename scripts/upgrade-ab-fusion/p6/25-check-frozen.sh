#!/usr/bin/env bash
# 冻结后 B 再写则失败. 先抓 current 再比 freeze.
set -euo pipefail
STEP="p6.25-frozen"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env

[[ -f "${LOG_DIR}/p6/freeze/summary.tsv" ]] || die "缺少 freeze 水位, 先 LABEL=freeze bash p6/10-capture-watermark.sh"

LABEL=current bash "${PACK_ROOT}/p6/10-capture-watermark.sh"
python3 "${PACK_ROOT}/p6/check_frozen.py" \
  --freeze "${LOG_DIR}/p6/freeze" \
  --current "${LOG_DIR}/p6/current"

ledger "${STEP}" "OK" ""
echo "OK ${STEP}"
