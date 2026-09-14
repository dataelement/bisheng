#!/usr/bin/env bash
# 对已导出 JSON 做 dry-run。映不上所有者则非 0 退出。不改库。
set -euo pipefail
STEP="p5.dry-run"
MYSQL_CONTAINER="${MYSQL_CONTAINER:-bisheng-mysql}"
MYSQL_DB="${MYSQL_DB:-bisheng}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
ledger "${STEP}" "START" ""

mkdir -p "${LOG_DIR}/p5"
user_map="${USER_MAP:-${LOG_DIR}/p5/fusion_user_map.csv}"
if [[ ! -f "${user_map}" ]]; then
  user_map="${PACK_ROOT}/p4/user-map.csv"
fi
[[ -f "${user_map}" ]] || die "缺少用户映射 ${user_map}。先跑 P4 或 10-inventory.sh"

out="${LOG_DIR}/p5/dry-run.json"
args=(
  --json-dir "${LOG_DIR}/p5"
  --user-map "${user_map}"
  --out "${out}"
)
[[ -f "${LOG_DIR}/p5/fusion_dept_map.csv" ]] && args+=(--dept-map "${LOG_DIR}/p5/fusion_dept_map.csv")
[[ -f "${LOG_DIR}/p5/b-space-names.tsv" ]] && args+=(--b-names "${LOG_DIR}/p5/b-space-names.tsv")
[[ -f "${LOG_DIR}/p5/b-favorites.csv" ]] && args+=(--b-favorites "${LOG_DIR}/p5/b-favorites.csv")
set +e
python3 "${PACK_ROOT}/p5/20-dry-run.py" "${args[@]}"
rc=$?
set -e
if [[ "${rc}" == "2" ]]; then
  ledger "${STEP}" "BLOCK" "${out}"
  if [[ "${P5_ALLOW_PARTIAL:-0}" == "1" ]]; then
    log "有空间所有者/部门作用域映不上, P5_ALLOW_PARTIAL=1 继续。见 ${out}"
  else
    die "有空间所有者映不上, 见 ${out}"
  fi
elif [[ "${rc}" != "0" ]]; then
  die "dry-run 失败 rc=${rc}"
else
  ledger "${STEP}" "OK" "${out}"
  log "dry-run 通过: ${out}"
fi
