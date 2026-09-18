#!/usr/bin/env bash
# 按冻结目录回滚 B.
# 完整冻结 (MANIFEST.complete_storage): 还原 MySQL+MinIO+Milvus+ES+etcd+compose.
#   APPLY=1 需要 CONFIRM_VERSION_ROLLBACK=1 CONFIRM_RESTORE_STORAGE=1
#   会覆盖 MANIFEST 里的 live_host, 应在隔离机上做.
# 不完整冻结 (本轮 20260911124114): 只还原 MySQL+compose, 必须 ACCEPT_INCOMPLETE_STORAGE=1.
set -euo pipefail
STEP="p2.90-rollback"
APPLY="${APPLY:-0}"
CONFIRM_VERSION_ROLLBACK="${CONFIRM_VERSION_ROLLBACK:-0}"
ACCEPT_INCOMPLETE_STORAGE="${ACCEPT_INCOMPLETE_STORAGE:-0}"
CONFIRM_RESTORE_STORAGE="${CONFIRM_RESTORE_STORAGE:-0}"
: "${BACKEND_CONTAINER:=bisheng-backend}"
: "${WORKER_CONTAINER:=bisheng-backend-worker}"
: "${FRONTEND_CONTAINER:=bisheng-frontend}"
: "${GATEWAY_CONTAINER:=bisheng-gateway}"
: "${BEAT_CONTAINER:=bisheng-backend-beat}"
: "${MYSQL_CONTAINER:=bisheng-mysql}"
: "${MYSQL_DB:=bisheng}"
: "${BACKUP_DIR:=/data/upgrade-backups}"
: "${OPENFGA_CONTAINER:=bisheng-openfga}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
# shellcheck source=../lib/freeze_storage.sh
source "$(cd "$(dirname "$0")/.." && pwd)/lib/freeze_storage.sh"
load_env
discover_deployment
assert_data_dir_nonempty "${MYSQL_CONTAINER}" /var/lib/mysql

if [[ -z "${BACKUP_STAMP:-}" && -f "${LOG_DIR}/p2/current-freeze.txt" ]]; then
  BACKUP_STAMP="$(tr -d '[:space:]' <"${LOG_DIR}/p2/current-freeze.txt" || true)"
fi
: "${BACKUP_STAMP:=20260911124114}"

report="${LOG_DIR}/p2/freeze-inspect.txt"
mkdir -p "${LOG_DIR}/p2"

inspect_out="$(python3 - "${PACK_ROOT}" "${BACKUP_DIR}" "${BACKUP_STAMP}" "${report}" <<'PY'
import json
import sys
from pathlib import Path

pack, backup_dir, stamp, report = sys.argv[1:5]
sys.path.insert(0, pack)
from fusion.version_rollback import inspect_freeze_dir, pick_freeze_dir

try:
    root = pick_freeze_dir(Path(backup_dir), stamp)
except (ValueError, FileNotFoundError) as exc:
    print(f"ERROR\t{exc}", file=sys.stderr)
    sys.exit(1)
info = inspect_freeze_dir(root)
Path(report).write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
if info["errors"]:
    for err in info["errors"]:
        print(f"ERROR\t{err}", file=sys.stderr)
    sys.exit(1)
print(info["dump"])
print(info["compose"])
print(info["config"])
print(info["backend_image"])
print("1" if info["sha_ok"] else "0")
print("1" if info.get("complete_storage") else "0")
print("1" if info.get("todo_storage") else "0")
print(info["root"])
PY
)"

dump="$(printf '%s\n' "${inspect_out}" | sed -n '1p')"
freeze_compose="$(printf '%s\n' "${inspect_out}" | sed -n '2p')"
freeze_config="$(printf '%s\n' "${inspect_out}" | sed -n '3p')"
backend_image="$(printf '%s\n' "${inspect_out}" | sed -n '4p')"
sha_ok="$(printf '%s\n' "${inspect_out}" | sed -n '5p')"
complete_storage="$(printf '%s\n' "${inspect_out}" | sed -n '6p')"
todo_storage="$(printf '%s\n' "${inspect_out}" | sed -n '7p')"
freeze_root="$(printf '%s\n' "${inspect_out}" | sed -n '8p')"

[[ -n "${dump}" && -f "${dump}" ]] || die "dump 路径空"
[[ -n "${freeze_compose}" && -f "${freeze_compose}" ]] || die "冻结 compose 路径空"
[[ "${sha_ok}" == "1" ]] || die "dump sha256 未通过"

log "冻结目录 ${BACKUP_DIR}/${BACKUP_STAMP}"
log "dump ${dump}"
log "compose backend image ${backend_image}"
log "完整存储=${complete_storage} 检查报告 ${report}"

preflight_report
if table_exists alembic_version; then
  log "当前 alembic_version=$(mysql_scalar "SELECT version_num FROM alembic_version LIMIT 1" || true)"
else
  log "当前无 alembic_version"
fi

print_fe_image() {
  python3 - "${freeze_compose}" <<'PY'
import re, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="ignore")
in_fe = False
for raw in text.splitlines():
    line = raw.rstrip()
    if re.match(r"^  frontend:\s*$", line):
        in_fe = True
        continue
    if in_fe and re.match(r"^  [A-Za-z0-9._-]+:\s*$", line):
        break
    if in_fe:
        m = re.match(r"^\s+image:\s+(\S+)\s*$", line)
        if m:
            print(m.group(1))
            break
PY
}

ensure_images() {
  docker image inspect "${backend_image}" >/dev/null 2>&1 \
    || die "本地没有镜像 ${backend_image}, 先 docker load"
  local fe_image
  fe_image="$(print_fe_image)"
  if [[ -n "${fe_image}" ]]; then
    docker image inspect "${fe_image}" >/dev/null 2>&1 \
      || die "本地没有镜像 ${fe_image}, 先 docker load"
  fi
}

mysql_root() {
  docker exec -i -e "SQL=$1" "${MYSQL_CONTAINER}" \
    sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -N -B -uroot --default-character-set=utf8mb4 -e "$SQL"'
}

safety_dump_and_import() {
  docker stop "${FRONTEND_CONTAINER}" "${GATEWAY_CONTAINER}" \
    "${BACKEND_CONTAINER}" "${WORKER_CONTAINER}" "${BEAT_CONTAINER}" \
    "${OPENFGA_CONTAINER}" bisheng-openfga-migrate >/dev/null 2>&1 || true
  safety="${BACKUP_DIR}/pre-rollback-$(date +%Y%m%d%H%M%S)"
  mkdir -p "${safety}"
  log "当前库另存 ${safety}/mysql-${MYSQL_DB}.sql"
  docker exec "${MYSQL_CONTAINER}" sh -c \
    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction --routines --triggers --databases '"${MYSQL_DB}" \
    >"${safety}/mysql-${MYSQL_DB}.sql"
  sha256_file "${safety}/mysql-${MYSQL_DB}.sql" >"${safety}/mysql-${MYSQL_DB}.sql.sha256"
  cp -a "${COMPOSE_FILE}" "${safety}/$(basename "${COMPOSE_FILE}").live"
  resolve_host_file_optional "${BACKEND_CONTAINER}" cfg_host "${CONFIG_YAML_DESTS[@]}"
  if [[ -n "${cfg_host}" ]]; then
    cp -a "${cfg_host}" "${safety}/config.yaml.live"
  fi
  while IFS= read -r pid; do
    [[ -n "${pid}" ]] || continue
    mysql_root "KILL ${pid}" 2>/dev/null || true
  done < <(mysql_root "SELECT ID FROM information_schema.PROCESSLIST WHERE DB='${MYSQL_DB}' AND ID <> CONNECTION_ID()")
  mysql_root "DROP DATABASE IF EXISTS \`${MYSQL_DB}\`"
  docker exec -i "${MYSQL_CONTAINER}" \
    sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot --default-character-set=utf8mb4 --max_allowed_packet=512M' \
    <"${dump}"
  table_exists knowledge || die "导入后没有 knowledge"
}

restore_compose_config() {
  cp -a "${COMPOSE_FILE}" "${COMPOSE_FILE}.bak.rollback.$(date +%Y%m%d%H%M%S)"
  cp -a "${freeze_compose}" "${COMPOSE_FILE}"
  _graft_mysql_password "${COMPOSE_FILE}"
  if [[ -n "${freeze_config}" && -n "${cfg_host:-}" ]]; then
    cp -a "${cfg_host}" "${cfg_host}.bak.rollback.$(date +%Y%m%d%H%M%S)"
    cp -a "${freeze_config}" "${cfg_host}"
  elif [[ -n "${freeze_config}" ]]; then
    log "WARN 当前 backend 没有 config.yaml bind mount, 冻结 config 未写入运行路径: ${freeze_config}"
  fi
  COMPOSE_CONFIG_FILES=("${COMPOSE_FILE}")
  COMPOSE_EXTRA_FILES=()
}

if [[ "${complete_storage}" == "1" ]]; then
  echo "将执行 (完整 §16 恢复):"
  echo "  1. 停 API/OpenFGA 和 MinIO/Milvus/ES/etcd"
  echo "  2. 当前库 dump 到 ${BACKUP_DIR}/pre-rollback-<时间>"
  echo "  3. DROP DATABASE ${MYSQL_DB} 后导入冻结 dump"
  echo "  4. rsync 冻结目录 storage/* 覆盖 MANIFEST.live_host"
  echo "  5. 覆盖 compose/config, 起存储再起 backend/worker/frontend"
  echo "隔离机: 不要在未确认的生产盘上 APPLY=1"
  if [[ "${APPLY}" != "1" ]]; then
    log "APPLY=0, 不写. APPLY=1 需要 CONFIRM_VERSION_ROLLBACK=1 CONFIRM_RESTORE_STORAGE=1"
    ledger "${STEP}" "OK" "APPLY=0 complete stamp=${BACKUP_STAMP}"
    echo "OK ${STEP} APPLY=0 complete stamp=${BACKUP_STAMP}"
    exit 0
  fi
  [[ "${CONFIRM_VERSION_ROLLBACK}" == "1" ]] || die "APPLY=1 需要 CONFIRM_VERSION_ROLLBACK=1"
  [[ "${CONFIRM_RESTORE_STORAGE}" == "1" ]] || die "完整恢复会覆盖对象存储, 需要 CONFIRM_RESTORE_STORAGE=1"
  [[ "${ACCEPT_INCOMPLETE_STORAGE}" != "1" ]] || die "完整冻结不要设 ACCEPT_INCOMPLETE_STORAGE"
  ensure_images
  minio_c="$(find_storage_container minio "bisheng-milvus-minio bisheng-minio" || true)"
  es_c="$(find_storage_container elasticsearch "bisheng-es bisheng-elasticsearch" || true)"
  etcd_c="$(find_storage_container etcd "bisheng-milvus-etcd" || true)"
  milvus_c="$(find_storage_container milvus "bisheng-milvus-standalone" || true)"
  log "停存储容器"
  docker stop "${milvus_c}" "${minio_c}" "${etcd_c}" "${es_c}" 2>/dev/null || true
  safety_dump_and_import
  log "rsync 存储副本到 live_host"
  while IFS=$'\t' read -r key src live; do
    [[ -n "${key}" ]] || continue
    [[ -d "${src}" ]] || die "缺少副本 ${key}: ${src}"
    [[ -n "${live}" && "${live}" != "/" && "${live}" != "." ]] || die "${key} live_host 非法: ${live}"
    log "restore ${key} -> ${live}"
    copy_tree "${src}" "${live}"
  done < <(python3 - "${PACK_ROOT}" "${freeze_root}" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from fusion.freeze_storage import STORAGE_KEYS, load_manifest
root = Path(sys.argv[2])
manifest = load_manifest(root)
if not manifest:
    raise SystemExit("缺少 MANIFEST.json")
storage = manifest.get("storage") or {}
for key in STORAGE_KEYS:
    item = storage.get(key) or {}
    rel = item.get("backup_rel") or ""
    live = item.get("live_host") or ""
    if not rel or not live:
        raise SystemExit(f"{key} 缺 backup_rel/live_host")
    if live in ("/", "", ".") or live.startswith("/proc"):
        raise SystemExit(f"{key} live_host 非法: {live}")
    print(f"{key}\t{root / rel}\t{live}")
PY
)
  restore_compose_config
  log "起 etcd/minio/elasticsearch/milvus 再起 API"
  compose up -d --no-deps etcd minio elasticsearch milvus || true
  compose up -d --no-deps backend backend_worker frontend
  ledger "${STEP}" "OK" "APPLY=1 complete stamp=${BACKUP_STAMP} safety=${safety}"
  echo "OK ${STEP} APPLY=1 complete stamp=${BACKUP_STAMP} safety=${safety}"
  echo "下一步: 登录, 开一条工作流和一个传统知识库, 抽检检索."
  exit 0
fi

if [[ "${todo_storage}" == "1" ]]; then
  log "WARN 冻结目录有 TODO-storage.txt"
fi
echo "将执行 (不完整, 不还原对象存储):"
echo "  1. 停 frontend/gateway/backend/worker/beat/openfga (mysql/minio/milvus/es 保持)"
echo "  2. 当前库 dump 到 ${BACKUP_DIR}/pre-rollback-<时间>"
echo "  3. DROP DATABASE ${MYSQL_DB} 后导入冻结 dump"
echo "  4. 覆盖 compose/config, compose up --no-deps backend backend_worker frontend"
echo "不会: 还原 MinIO/Milvus/ES"

if [[ "${APPLY}" != "1" ]]; then
  log "APPLY=0, 不写. 不完整冻结 APPLY=1 需要 CONFIRM_VERSION_ROLLBACK=1 ACCEPT_INCOMPLETE_STORAGE=1"
  ledger "${STEP}" "OK" "APPLY=0 incomplete stamp=${BACKUP_STAMP}"
  echo "OK ${STEP} APPLY=0 incomplete stamp=${BACKUP_STAMP}"
  exit 0
fi

[[ "${CONFIRM_VERSION_ROLLBACK}" == "1" ]] || die "APPLY=1 需要 CONFIRM_VERSION_ROLLBACK=1"
[[ "${ACCEPT_INCOMPLETE_STORAGE}" == "1" ]] || die "不完整冻结 APPLY=1 需要 ACCEPT_INCOMPLETE_STORAGE=1"
ensure_images
safety_dump_and_import
if table_exists department; then
  die "导入后仍有 department, dump 可能不是 2.4 或未 DROP 成功"
fi
column_exists knowledge auth_type || die "导入后没有 knowledge.auth_type, 不像 2.4"
if table_exists alembic_version; then
  n="$(mysql_scalar "SELECT COUNT(*) FROM alembic_version")"
  [[ "${n}" == "0" ]] || die "导入后 alembic_version 仍有 ${n} 行, 拒绝继续"
fi
restore_compose_config
compose up -d --no-deps backend backend_worker frontend
ledger "${STEP}" "OK" "APPLY=1 incomplete stamp=${BACKUP_STAMP} safety=${safety}"
echo "OK ${STEP} APPLY=1 incomplete stamp=${BACKUP_STAMP} safety=${safety}"
echo "下一步: 登录, 开一条工作流和一个传统知识库. 检索对不上是对象存储未冻结的代价."
