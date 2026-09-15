#!/usr/bin/env bash
# 迁入工作流/助手上线. INSERT 仍强制 status=1; 本步才改 2.
# APPLY=1 还要 CONFIRM_PUBLISH_FLOWS=1. 不跑端到端, 只做静态门禁.
set -euo pipefail
STEP="p5.36-publish"
APPLY="${APPLY:-0}"
CONFIRM_PUBLISH_FLOWS="${CONFIRM_PUBLISH_FLOWS:-0}"
BATCH_NO="${BATCH_NO:-fusion-$(date +%Y%m%d)}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"

[[ -f "${LOG_DIR}/p5/dump.json" ]] || die "缺少 dump.json, 先跑 p5/30-apply.sh"
[[ -d "${LOG_DIR}/p4/maps" ]] || die "缺少 maps"

python3 "${PACK_ROOT}/p5/build_publish.py" \
  --dump "${LOG_DIR}/p5/dump.json" \
  --maps "${LOG_DIR}/p4/maps" \
  --out "${LOG_DIR}/p5/publish.sql" \
  --batch "${BATCH_NO}" \
  --gaps "${LOG_DIR}/p5/gaps-model-tool.tsv" \
  --vector-exceptions "${LOG_DIR}/p5/vector-exceptions.tsv"

if [[ "${APPLY}" == "1" ]]; then
  [[ "${CONFIRM_PUBLISH_FLOWS}" == "1" ]] || die "发布 APPLY=1 需要 CONFIRM_PUBLISH_FLOWS=1"
  require_a_25_for_apply
  apply_sql_on_a "${LOG_DIR}/p5/publish.sql"
fi

ledger "${STEP}" "OK" "APPLY=${APPLY}"
echo "OK ${STEP}. 门禁 ${LOG_DIR}/p5/publish-gate.tsv ; 端到端仍须在 A UI 验收"
