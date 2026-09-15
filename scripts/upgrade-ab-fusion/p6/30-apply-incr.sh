#!/usr/bin/env bash
# 冻结检查 -> 增量 DELETE/UPDATE -> 再跑 30-apply 只补新行 (skip 已映射).
set -euo pipefail
STEP="p6.30-incr"
APPLY="${APPLY:-0}"
BATCH_NO="${BATCH_NO:-fusion-$(date +%Y%m%d)}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"

bash "${PACK_ROOT}/p6/25-check-frozen.sh"
bash "${PACK_ROOT}/p5/10-export-b-business.sh"
python3 "${PACK_ROOT}/p5/assemble_dump.py" "${LOG_DIR}/p5"
bash "${PACK_ROOT}/p6/20-diff-watermark.sh"

mkdir -p "${LOG_DIR}/p4/maps"
cp -f "${PACK_ROOT}/p4/"*.csv "${LOG_DIR}/p4/maps/" 2>/dev/null || true

python3 "${PACK_ROOT}/p6/build_incr.py" \
  --dump "${LOG_DIR}/p5/dump.json" \
  --maps "${LOG_DIR}/p4/maps" \
  --diff "${LOG_DIR}/p6" \
  --out-dir "${LOG_DIR}/p5" \
  --batch "${BATCH_NO}"

if [[ "${APPLY}" == "1" ]]; then
  require_a_25_for_apply
  require_b_25_for_apply
  apply_sql_on_a "${LOG_DIR}/p5/incr-delete.sql"
  apply_sql_on_a "${LOG_DIR}/p5/incr-update.sql"
fi

APPLY="${APPLY}" BATCH_NO="${BATCH_NO}" bash "${PACK_ROOT}/p5/30-apply.sh"

ledger "${STEP}" "OK" "APPLY=${APPLY}"
echo "OK ${STEP}. 下一步: APPLY=${APPLY} bash p5/20-copy-minio.sh ; bash p5/22-copy-vectors.sh ; bash p5/50-retrieve-gold.sh"
