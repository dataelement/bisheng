#!/usr/bin/env bash
# dry-run + 生成各域 SQL. APPLY=1 才写入 A.
set -euo pipefail
STEP="p5.30-apply"
APPLY="${APPLY:-0}"
BATCH_NO="${BATCH_NO:-fusion-$(date +%Y%m%d)}"
MIGRATE_B_SPACES="${MIGRATE_B_SPACES:-0}"
CONFIRM_POINTS="${CONFIRM_POINTS:-0}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"

[[ -f "${PACK_ROOT}/p4/user-map.csv" ]] || die "先完成身份映射 p4/user-map.csv"

if [[ "${APPLY}" == "1" ]]; then
  require_a_25_for_apply
  require_b_25_for_apply
  assert_b_org_sync_off
  assert_a_shared_space_gate
fi

mkdir -p "${LOG_DIR}/p5" "${LOG_DIR}/p4/maps"
cp -f "${PACK_ROOT}/p4/"*.csv "${LOG_DIR}/p4/maps/" 2>/dev/null || true
rm -f "${LOG_DIR}/p5/minio-jobs.tsv"

python3 "${PACK_ROOT}/p5/assemble_dump.py" "${LOG_DIR}/p5"
dry_space=(--no-migrate-b-spaces)
if [[ "${MIGRATE_B_SPACES}" == "1" ]]; then
  dry_space=(--migrate-b-spaces)
fi
python3 "${PACK_ROOT}/fusion/cli.py" dry-run \
  --input "${LOG_DIR}/p5/dump.json" \
  --user-map "${PACK_ROOT}/p4/user-map.csv" \
  --out "${LOG_DIR}/p5/dry-run.json" \
  "${dry_space[@]}"

# 字典可先于业务; QA/标签依赖 knowledge-map; 组可见性依赖资源 map
for kind in dictionary knowledge qa tags flow assistant session citations marks reports tool_types relations group_resource role_access openfga; do
  python3 "${PACK_ROOT}/p5/build_sql.py" --kind "${kind}" \
    --dump "${LOG_DIR}/p5/dump.json" \
    --maps "${LOG_DIR}/p4/maps" \
    --out "${LOG_DIR}/p5/${kind}.sql" \
    --batch "${BATCH_NO}"
done

python3 "${PACK_ROOT}/fusion/cli.py" gaps \
  --maps "${LOG_DIR}/p4/maps" \
  --propose-dir "${LOG_DIR}/p4" \
  --out "${LOG_DIR}/p5/gaps-model-tool.tsv"

if [[ "${CONFIRM_POINTS}" == "1" ]]; then
  log "积分迁移未实现自动 APPLY, 见方案 D16; 本包默认跳过"
fi

if [[ "${APPLY}" == "1" ]]; then
  for kind in dictionary knowledge qa tags flow assistant session citations marks reports tool_types relations group_resource role_access; do
    apply_sql_on_a "${LOG_DIR}/p5/${kind}.sql"
  done
fi

ledger "${STEP}" "OK" "APPLY=${APPLY}"
echo "OK ${STEP}. MinIO 任务 logs/p5/minio-jobs.tsv; OpenFGA logs/p5/openfga.tuples.json; 缺口 logs/p5/gaps-model-tool.tsv"
echo "下一步: bash p5/20-copy-minio.sh ; bash p5/22-copy-vectors.sh ; bash p5/35-apply-openfga.sh"
