#!/usr/bin/env bash
# A→B 全迁编排。默认 APPLY=0, 只导出/生成 SQL/dry-run, 不落库。
# 不迁: A 传统库 type=0、工作流/助手/工具、会话/审计、Token、物理拷 ES/Milvus/OpenFGA、
#       打开首钢同步、发布空间/切 DNS。
# APPLY=1 还要 CONFIRM_FULL_MIGRATE=1。
set -euo pipefail
STEP="full-migrate"
APPLY="${APPLY:-0}"
CONFIRM_FULL_MIGRATE="${CONFIRM_FULL_MIGRATE:-0}"
BATCH_NO="${BATCH_NO:-full-$(date +%Y%m%d)}"
ALL_SPACES="${ALL_SPACES:-1}"
STAGE="all"
MYSQL_CONTAINER="${MYSQL_CONTAINER:-bisheng-mysql}"
MYSQL_DB="${MYSQL_DB:-bisheng}"

usage() {
  cat <<'EOF'
用法:
  bash full-migrate.sh                 # 默认 APPLY=0 跑完全部可自动阶段
  bash full-migrate.sh --stage users-export
  APPLY=0 bash full-migrate.sh
  APPLY=1 CONFIRM_FULL_MIGRATE=1 bash full-migrate.sh   # 真落库, 需人工已签字 CSV

阶段顺序:
  users-export → users-propose → users-apply
  depts-export → depts-propose → depts-apply
  spaces-export → spaces-inventory → spaces-dry-run → spaces-apply
  relations-export → relations-apply
  points-export → points-apply

门禁:
  users-apply / depts-apply 的 APPLY=1 需要 p4/user-map.csv、p4/dept-map.csv (签字副本)
  部门冲突未关闭时 APPLY=1 还要 CONFIRM_DEPT_HIERARCHY=1
EOF
}

# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --stage)
      STAGE="$2"
      shift 2
      ;;
    --all-spaces)
      ALL_SPACES=1
      shift
      ;;
    --spaces-file)
      ALL_SPACES=0
      mkdir -p "${LOG_DIR}/p5"
      cp "$2" "${LOG_DIR}/p5/batch.txt"
      shift 2
      ;;
    *)
      die "未知参数 $1"
      ;;
  esac
done

if [[ "${APPLY}" == "1" && "${CONFIRM_FULL_MIGRATE}" != "1" ]]; then
  die "全迁 APPLY=1 需要同时 CONFIRM_FULL_MIGRATE=1。默认只生成 SQL。"
fi

export APPLY BATCH_NO
if [[ "${APPLY}" != "1" ]]; then
  export P5_ALLOW_PARTIAL="${P5_ALLOW_PARTIAL:-1}"
fi
export USER_MAP="${USER_MAP:-${PACK_ROOT}/p4/user-map.csv}"
mkdir -p "${LOG_DIR}/p4" "${LOG_DIR}/p5"
ledger "${STEP}" "START" "APPLY=${APPLY} stage=${STAGE} batch=${BATCH_NO}"

signed_user_map() {
  [[ -f "${PACK_ROOT}/p4/user-map.csv" ]]
}

signed_dept_map() {
  [[ -f "${PACK_ROOT}/p4/dept-map.csv" ]]
}

copy_dept_map_for_dry() {
  if signed_dept_map; then
    python3 - "${PACK_ROOT}/p4/dept-map.csv" "${LOG_DIR}/p5/fusion_dept_map.csv" <<'PY'
import csv, sys
from pathlib import Path
src, dst = Path(sys.argv[1]), Path(sys.argv[2])
rows = []
with src.open(encoding="utf-8") as f:
    filtered = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
for row in csv.DictReader(filtered):
    rows.append(row)
dst.parent.mkdir(parents=True, exist_ok=True)
with dst.open("w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["a_dept_pk", "b_dept_pk", "external_id", "action"])
    w.writeheader()
    for row in rows:
        w.writerow({k: row.get(k, "") for k in ["a_dept_pk", "b_dept_pk", "external_id", "action"]})
PY
  elif [[ -f "${LOG_DIR}/p4/dept-map.proposed.csv" ]]; then
    python3 - "${LOG_DIR}/p4/dept-map.proposed.csv" "${LOG_DIR}/p5/fusion_dept_map.csv" <<'PY'
import csv, sys
from pathlib import Path
src, dst = Path(sys.argv[1]), Path(sys.argv[2])
with src.open(encoding="utf-8") as f:
    filtered = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
rows = list(csv.DictReader(filtered))
dst.parent.mkdir(parents=True, exist_ok=True)
with dst.open("w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["a_dept_pk", "b_dept_pk", "external_id", "action"])
    w.writeheader()
    for row in rows:
        w.writerow({k: row.get(k, "") for k in ["a_dept_pk", "b_dept_pk", "external_id", "action"]})
PY
  fi
}

run_stage() {
  local name="$1"
  log "=== ${name} ==="
  case "${name}" in
    users-export)
      bash "${PACK_ROOT}/p4/00-export-a-users.sh"
      ;;
    users-propose)
      python3 "${PACK_ROOT}/p4/01-propose-map.py" \
        "${LOG_DIR}/p4/a-users.csv" "${LOG_DIR}/p4/b-users.csv" --out-dir "${LOG_DIR}/p4"
      ;;
    users-apply)
      if ! signed_user_map; then
        log "没有 p4/user-map.csv, 跳过 users-apply。把 logs/p4/user-map.proposed.csv 签字复制过去。"
        return 0
      fi
      BATCH_NO="${BATCH_NO}" bash "${PACK_ROOT}/p4/apply-takeover.sh" "${PACK_ROOT}/p4/user-map.csv"
      ;;
    depts-export)
      bash "${PACK_ROOT}/p4/02-export-a-depts.sh"
      ;;
    depts-propose)
      python3 "${PACK_ROOT}/p4/03-propose-dept-map.py" \
        "${LOG_DIR}/p4/a-depts.tsv" "${LOG_DIR}/p4/b-depts.tsv" --out-dir "${LOG_DIR}/p4"
      copy_dept_map_for_dry
      ;;
    depts-apply)
      if ! signed_dept_map; then
        log "没有 p4/dept-map.csv, 跳过 depts-apply。把 logs/p4/dept-map.proposed.csv 签字复制过去。"
        copy_dept_map_for_dry
        return 0
      fi
      BATCH_NO="${BATCH_NO}" bash "${PACK_ROOT}/p4/04-apply-depts.sh" "${PACK_ROOT}/p4/dept-map.csv"
      copy_dept_map_for_dry
      ;;
    spaces-export)
      if [[ "${ALL_SPACES}" == "1" ]]; then
        bash "${PACK_ROOT}/p5/00-export-a-space.sh" --all
      else
        bash "${PACK_ROOT}/p5/00-export-a-space.sh"
      fi
      ;;
    spaces-inventory)
      bash "${PACK_ROOT}/p5/10-inventory.sh"
      copy_dept_map_for_dry
      ;;
    spaces-dry-run)
      if [[ ! -f "${PACK_ROOT}/p4/user-map.csv" && ! -f "${LOG_DIR}/p5/fusion_user_map.csv" ]]; then
        log "没有用户映射, 跳过 spaces-dry-run"
        return 0
      fi
      P5_ALLOW_PARTIAL="${P5_ALLOW_PARTIAL:-0}" bash "${PACK_ROOT}/p5/20-dry-run.sh"
      ;;
    spaces-apply)
      if [[ ! -f "${LOG_DIR}/p5/dry-run.json" ]]; then
        log "没有 dry-run.json, 跳过 spaces-apply"
        return 0
      fi
      BATCH_NO="${BATCH_NO}" bash "${PACK_ROOT}/p5/30-apply.sh"
      ;;
    relations-export)
      bash "${PACK_ROOT}/p5/50-export-a-relations.sh"
      ;;
    relations-apply)
      if [[ ! -f "${LOG_DIR}/p5/a-relations.json" ]]; then
        log "没有 a-relations.json, 跳过 relations-apply"
        return 0
      fi
      BATCH_NO="${BATCH_NO}" bash "${PACK_ROOT}/p5/51-apply-relations.sh"
      ;;
    points-export)
      bash "${PACK_ROOT}/p4/10-export-a-points.sh"
      ;;
    points-apply)
      if [[ ! -f "${LOG_DIR}/p4/a-points.json" ]]; then
        log "没有 a-points.json, 跳过 points-apply"
        return 0
      fi
      BATCH_NO="${BATCH_NO}" bash "${PACK_ROOT}/p4/11-apply-points.sh"
      ;;
    *)
      die "未知阶段 ${name}"
      ;;
  esac
}

ALL_STAGES=(
  users-export
  users-propose
  users-apply
  depts-export
  depts-propose
  depts-apply
  spaces-export
  spaces-inventory
  spaces-dry-run
  spaces-apply
  relations-export
  relations-apply
  points-export
  points-apply
)

if [[ "${STAGE}" == "all" ]]; then
  for s in "${ALL_STAGES[@]}"; do
    run_stage "${s}"
  done
else
  run_stage "${STAGE}"
fi

ledger "${STEP}" "OK" "APPLY=${APPLY} stage=${STAGE}"
log "全迁编排结束 APPLY=${APPLY}。SQL 在 logs/。APPLY=0 时 B 未改库。"
if [[ "${APPLY}" != "1" ]]; then
  log "签字: cp logs/p4/user-map.proposed.csv p4/user-map.csv"
  log "签字: cp logs/p4/dept-map.proposed.csv p4/dept-map.csv"
  log "落库: APPLY=1 CONFIRM_FULL_MIGRATE=1 bash full-migrate.sh"
fi
