#!/usr/bin/env bash
# 对 dry-run 通过的空间 APPLY。默认 APPLY=0 只打印。
# 用法: bash p5/30-apply.sh --space-id 123
#       bash p5/30-apply.sh   # 处理 dry-run.json 里全部 ok 空间
set -euo pipefail
STEP="p5.apply"
MYSQL_CONTAINER="${MYSQL_CONTAINER:-bisheng-mysql}"
MYSQL_DB="${MYSQL_DB:-bisheng}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-bisheng-backend}"
A_BACKEND_CONTAINER="${A_BACKEND_CONTAINER:-bisheng-backend}"
APPLY="${APPLY:-0}"
BATCH_NO="${BATCH_NO:-p5-$(date +%Y%m%d)}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"
ledger "${STEP}" "START" "APPLY=${APPLY} batch=${BATCH_NO}"

mkdir -p "${LOG_DIR}/p5/objects"
dry="${LOG_DIR}/p5/dry-run.json"
[[ -f "${dry}" ]] || die "缺少 ${dry}，先跑 p5/20-dry-run.sh"
user_map="${USER_MAP:-${LOG_DIR}/p5/fusion_user_map.csv}"
if [[ ! -f "${user_map}" ]]; then
  user_map="${PACK_ROOT}/p4/user-map.csv"
fi
dept_map="${LOG_DIR}/p5/fusion_dept_map.csv"
manifest="${LOG_DIR}/p5/rollback-manifest-${BATCH_NO}.json"

ids=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --space-id)
      ids+=("$2")
      shift 2
      ;;
    *)
      die "未知参数 $1"
      ;;
  esac
done

mapfile -t planned < <(python3 - "${dry}" "${ids[@]:-}" <<'PY'
import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
want = {int(x) for x in sys.argv[2:] if x}
for row in data.get("spaces") or []:
    sid = int(row["a_space_id"])
    if want and sid not in want:
        continue
    if not row.get("ok"):
        print(f"skip-blocked {sid}", file=sys.stderr)
        continue
    print(sid)
PY
)
[[ ${#planned[@]} -gt 0 ]] || die "没有 dry-run 通过的空间"

if [[ "${APPLY}" == "1" ]]; then
  require_b_25_for_apply
  assert_b_shared_storage_off
  assert_b_org_sync_off
  mysql_file "${PACK_ROOT}/p4/sql/mapping-tables.sql"
  mysql_file "${PACK_ROOT}/p5/sql/space-map.sql"
fi

install_py() {
  local host="$1" container="$2"
  if [[ "${host}" == "local" ]]; then
    docker exec "${container}" mkdir -p /tmp/fusion-ab
    docker cp "${PACK_ROOT}/p5/minio_xfer.py" "${container}:/tmp/fusion-ab/minio_xfer.py"
    docker cp "${PACK_ROOT}/p5/apply_ingest.py" "${container}:/tmp/fusion-ab/apply_ingest.py"
    docker cp "${PACK_ROOT}/p5/apply_space.py" "${container}:/tmp/fusion-ab/apply_space.py"
  else
    fusion_ssh_a docker exec "${container}" mkdir -p /tmp/fusion-ab
    # scp 脚本到 A 再 docker cp。密码仅用会话 SSHPASS。
    if [[ -n "${SSHPASS:-}" ]] && command -v sshpass >/dev/null 2>&1; then
      sshpass -e scp -P "${A_SSH_PORT}" -o StrictHostKeyChecking=accept-new \
        "${PACK_ROOT}/p5/minio_xfer.py" "${A_SSH_USER}@${A_SSH_HOST}:/tmp/minio_xfer.py"
    else
      scp -P "${A_SSH_PORT}" -o StrictHostKeyChecking=accept-new \
        "${PACK_ROOT}/p5/minio_xfer.py" "${A_SSH_USER}@${A_SSH_HOST}:/tmp/minio_xfer.py"
    fi
    fusion_ssh_a docker cp /tmp/minio_xfer.py "${container}:/tmp/fusion-ab/minio_xfer.py"
  fi
}

pull_objects() {
  local sid="$1"
  local json="${LOG_DIR}/p5/a-space-${sid}.json"
  local dest_dir="${LOG_DIR}/p5/objects/${sid}"
  mkdir -p "${dest_dir}"
  mapfile -t objs < <(python3 - "${json}" <<'PY'
import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for f in data.get("files") or []:
    if int(f.get("file_type") or 1) != 1:
        continue
    key = f.get("object_name") or ""
    if not key:
        continue
    print(f"{f['id']}\t{key}")
PY
)
  if [[ ${#objs[@]} -eq 0 ]]; then
    return 0
  fi
  if [[ "${APPLY}" != "1" ]]; then
    log "APPLY=0 space=${sid} 将拷 ${#objs[@]} 个 MinIO 对象"
    return 0
  fi
  install_py remote "${A_BACKEND_CONTAINER}"
  for item in "${objs[@]}"; do
    local fid="${item%%$'\t'*}"
    local key="${item#*$'\t'}"
    local local_file="${dest_dir}/${fid}"
    if [[ -f "${local_file}" ]]; then
      log "skip existing object a_file_id=${fid}"
      continue
    fi
    log "pull A object a_file_id=${fid}"
    if ! fusion_ssh_a docker exec -w "${BACKEND_WORKDIR}" -e PYTHONPATH="${BACKEND_WORKDIR}" \
      "${A_BACKEND_CONTAINER}" python /tmp/fusion-ab/minio_xfer.py get "${key}" "/tmp/fusion-obj-${fid}"; then
      log "WARN 拉对象失败 a_file_id=${fid} key=${key}"
      continue
    fi
    fusion_ssh_a docker cp "${A_BACKEND_CONTAINER}:/tmp/fusion-obj-${fid}" "/tmp/fusion-obj-${fid}"
    fusion_scp_from_a "/tmp/fusion-obj-${fid}" "${local_file}"
    fusion_ssh_a rm -f "/tmp/fusion-obj-${fid}" || true
  done
}

run_apply() {
  local sid="$1"
  local json="${LOG_DIR}/p5/a-space-${sid}.json"
  [[ -f "${json}" ]] || die "缺少 ${json}"
  pull_objects "${sid}"
  if [[ "${APPLY}" != "1" ]]; then
    log "APPLY=0 space=${sid} 将拷对象并在 B 隐藏创建新空间 (见 dry-run.json)"
    return 0
  fi
  install_py local "${BACKEND_CONTAINER}"
  docker exec "${BACKEND_CONTAINER}" mkdir -p "/tmp/fusion-ab/objects/${sid}" /tmp/fusion-ab/in
  docker cp "${json}" "${BACKEND_CONTAINER}:/tmp/fusion-ab/in/space.json"
  docker cp "${dry}" "${BACKEND_CONTAINER}:/tmp/fusion-ab/in/dry-run.json"
  docker cp "${user_map}" "${BACKEND_CONTAINER}:/tmp/fusion-ab/in/user-map.csv"
  if [[ -f "${dept_map}" ]]; then
    docker cp "${dept_map}" "${BACKEND_CONTAINER}:/tmp/fusion-ab/in/dept-map.csv"
  else
    docker exec "${BACKEND_CONTAINER}" sh -c 'echo a_dept_pk,b_dept_pk,external_id,action > /tmp/fusion-ab/in/dept-map.csv'
  fi
  if [[ -d "${LOG_DIR}/p5/objects/${sid}" ]]; then
    docker cp "${LOG_DIR}/p5/objects/${sid}/." "${BACKEND_CONTAINER}:/tmp/fusion-ab/objects/${sid}/"
  fi
  docker exec -w "${BACKEND_WORKDIR}" \
    -e PYTHONPATH="${BACKEND_WORKDIR}:/tmp/fusion-ab" \
    "${BACKEND_CONTAINER}" \
    python /tmp/fusion-ab/apply_space.py \
      --export-json /tmp/fusion-ab/in/space.json \
      --dry-run /tmp/fusion-ab/in/dry-run.json \
      --user-map /tmp/fusion-ab/in/user-map.csv \
      --dept-map /tmp/fusion-ab/in/dept-map.csv \
      --object-dir "/tmp/fusion-ab/objects/${sid}" \
      --batch-no "${BATCH_NO}" \
      --manifest /tmp/fusion-ab/in/rollback-manifest.json \
      --apply
  docker cp "${BACKEND_CONTAINER}:/tmp/fusion-ab/in/rollback-manifest.json" "${manifest}" 2>/dev/null || true
}

for sid in "${planned[@]}"; do
  run_apply "${sid}"
done

if [[ "${APPLY}" != "1" ]]; then
  ledger "${STEP}" "DRY" "spaces=${#planned[@]}"
  log "APPLY=0，未落库。确认后再 APPLY=1 bash p5/30-apply.sh --space-id <id>"
  exit 0
fi
ledger "${STEP}" "OK" "batch=${BATCH_NO} manifest=${manifest}"
log "apply 完成。回滚清单 ${manifest}。verify: bash p5/40-verify.sh"
