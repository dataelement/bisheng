#!/usr/bin/env bash
# 从 B 本机 OpenFGA 导出 Tuple jsonl, 供部门/角色授权重写. 失败不阻断主导出.
set -euo pipefail
STEP="p5.12-openfga-export"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
: "${B_OPENFGA_URL:=http://127.0.0.1:8080}"
: "${OPENFGA_STORE_NAME:=bisheng}"
mkdir -p "${LOG_DIR}/p5"
out="${LOG_DIR}/p5/b-openfga-tuples.jsonl"
if python3 "${PACK_ROOT}/p5/export_b_openfga.py" \
  "${B_OPENFGA_URL}" "${OPENFGA_STORE_NAME}" "${out}"; then
  ledger "${STEP}" "OK" "${out}"
  echo "OK ${STEP} ${out}"
  exit 0
fi
: > "${out}"
ledger "${STEP}" "SKIP" "B OpenFGA unreachable"
echo "SKIP ${STEP} (B OpenFGA 不可达, 部门授权仅 roleaccess)"
exit 0
