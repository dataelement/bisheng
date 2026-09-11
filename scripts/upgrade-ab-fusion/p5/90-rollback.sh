#!/usr/bin/env bash
# 只删 rollback-manifest 里的本批新空间/对象/tuple, 不动 B 原数据。默认 APPLY=0。
set -euo pipefail
STEP="p5.rollback"
MYSQL_CONTAINER="${MYSQL_CONTAINER:-bisheng-mysql}"
MYSQL_DB="${MYSQL_DB:-bisheng}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-bisheng-backend}"
APPLY="${APPLY:-0}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
ledger "${STEP}" "START" "APPLY=${APPLY}"

manifest="${1:-}"
if [[ -z "${manifest}" ]]; then
  shopt -s nullglob
  files=("${LOG_DIR}/p5"/rollback-manifest-*.json)
  [[ ${#files[@]} -gt 0 ]] || die "用法: bash p5/90-rollback.sh logs/p5/rollback-manifest-BATCH.json"
  manifest="${files[$((${#files[@]} - 1))]}"
fi
[[ -f "${manifest}" ]] || die "找不到 ${manifest}"
log "manifest=${manifest}"

docker exec "${BACKEND_CONTAINER}" mkdir -p /tmp/fusion-ab/in
docker cp "${PACK_ROOT}/p5/rollback_space.py" "${BACKEND_CONTAINER}:/tmp/fusion-ab/rollback_space.py"
docker cp "${manifest}" "${BACKEND_CONTAINER}:/tmp/fusion-ab/in/rollback-manifest.json"

args=(python /tmp/fusion-ab/rollback_space.py --manifest /tmp/fusion-ab/in/rollback-manifest.json)
if [[ "${APPLY}" == "1" ]]; then
  args+=(--apply)
else
  log "APPLY=0，只打印将删除的 B 新 ID"
fi
docker exec -w /app -e PYTHONPATH=/app:/tmp/fusion-ab "${BACKEND_CONTAINER}" "${args[@]}"

if [[ "${APPLY}" != "1" ]]; then
  ledger "${STEP}" "DRY" "${manifest}"
  exit 0
fi
ledger "${STEP}" "OK" "${manifest}"
log "本批新资源已删。B 原空间未动。"
