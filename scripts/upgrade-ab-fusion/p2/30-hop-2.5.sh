#!/usr/bin/env bash
# 2.4.0 -> 2.5.0-sg：OpenFGA + 换镜像 + 两段 Alembic + create_all。
# 禁止 stamp head。禁止把 entrypoint 的 WARNING-continue 当成功。
# 不含 F006 / 工作台，下一步 31-f006-workstation.sh。
set -euo pipefail
STEP="p2.30-2.5"
# 默认值可被环境变量覆盖；compose 路径与宿主机文件位置一律自动发现，不写死。
# 演练机（docker load 的 v2.5.0-sg 无 RepoDigest，只认 tag）需 export DRILL=1。
: "${DRILL:=0}"
: "${TARGET_BACKEND_IMAGE:=dataelement/bisheng-backend:v2.5.0-sg}"
: "${TARGET_FRONTEND_IMAGE:=dataelement/bisheng-frontend:v2.5.0-sg}"
: "${TARGET_ALEMBIC_HEAD:=f058_dashboard_dataset_flags}"
: "${ALEMBIC_BEFORE_DEPT:=f011_backfill_create_knowledge_web_menu}"
# OpenFGA 无 D02 digest，版本钉死；拉不到就覆盖这个变量。
: "${IMAGE_OPENFGA:=openfga/openfga:v1.8.12}"
: "${BACKEND_CONTAINER:=bisheng-backend}"
: "${WORKER_CONTAINER:=bisheng-backend-worker}"
: "${FRONTEND_CONTAINER:=bisheng-frontend}"
: "${MYSQL_CONTAINER:=bisheng-mysql}"
: "${MYSQL_DB:=bisheng}"
: "${APPLY:=0}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
discover_deployment
find_pack_docker

# 宿主机上这两个文件本 hop 要改，位置从容器挂载反查，
# 不按 compose 目录拼路径（现场可能设了 DOCKER_VOLUME_DIRECTORY）。
resolve_host_file "${BACKEND_CONTAINER}" CONFIG_FILE "${CONFIG_YAML_DESTS[@]}"
# entrypoint 允许没挂载（那就用镜像自带的），所以用 optional 版本。
resolve_host_file_optional "${BACKEND_CONTAINER}" ENTRYPOINT_HOST "${ENTRYPOINT_DESTS[@]}"
HOP_OVERRIDE="${COMPOSE_WORKDIR%/}/docker-compose.hop-2.5.override.yml"

# 叠加 hop override，其余 -f / -p / --project-directory 交给 compose() 统一处理。
compose_hop() {
  COMPOSE_EXTRA_FILES=("${HOP_OVERRIDE}")
  compose "$@"
  COMPOSE_EXTRA_FILES=()
}

alembic_current() {
  docker exec -e PYTHONPATH=./ -w /app "${BACKEND_CONTAINER}" \
    bash -lc 'alembic current' | awk '/^f[0-9]|^[0-9a-f]{12}/{print $1; exit}'
}

wait_container() {
  local name="$1" n=0
  while [[ "${n}" -lt 60 ]]; do
    if docker inspect -f '{{.State.Running}}' "${name}" 2>/dev/null | grep -q true; then
      return 0
    fi
    sleep 2
    n=$((n + 1))
  done
  die "容器未起来: ${name}"
}

wait_health() {
  local n=0
  while [[ "${n}" -lt 60 ]]; do
    if curl -sf http://127.0.0.1:7860/health >/dev/null; then
      return 0
    fi
    sleep 5
    n=$((n + 1))
  done
  die "/health 超时"
}

ledger "${STEP}" "START" "head=${TARGET_ALEMBIC_HEAD}"
if [[ "${TARGET_BACKEND_IMAGE}" == *"@sha256:"* ]]; then
  assert_pinned_image "${TARGET_BACKEND_IMAGE}"
fi
if [[ "${TARGET_FRONTEND_IMAGE}" == *"@sha256:"* ]]; then
  assert_pinned_image "${TARGET_FRONTEND_IMAGE}"
fi
[[ -f "${CONFIG_FILE}" ]] || die "找不到 config.yaml: ${CONFIG_FILE}"

preflight_report
# 卷指错位置时后面的 alembic 会在一个崭新空库上一路建表成功，必须先挡住。
assert_data_dir_nonempty "${MYSQL_CONTAINER}" /var/lib/mysql

if [[ "${DRILL:-0}" != "1" ]]; then
  log "非演练机，确认 TARGET_* 已改成生产制品"
fi

if ! require_apply; then
  ledger "${STEP}" "DRY" "APPLY=0"
  exit 0
fi
require_layout_confirmed

column_exists knowledge auth_type || die "knowledge.auth_type 不存在，先做完 2.4 hop"
column_exists knowledgefile file_level_path || die "knowledgefile.file_level_path 不存在，先做完 2.4 hop"

log "1) 建 openfga 库"
docker exec -i "${MYSQL_CONTAINER}" sh -c \
  'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --default-character-set=utf8mb4 -e "CREATE DATABASE IF NOT EXISTS openfga DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"'

ensure_image() {
  local img="$1"
  if docker image inspect "${img}" >/dev/null 2>&1; then
    log "本地已有 ${img}"
    return 0
  fi
  log "本地没有，pull ${img}"
  docker pull "${img}" || die "拉不到 ${img}。先 docker load D02 制品，或改脚本开头的镜像"
}

log "2) 用压缩包 docker/ 整份覆盖现场 compose / config.yaml / entrypoint / nginx"
replace_live_deploy_configs
# 压缩包里的镜像 tag 可能和本次 TARGET_* 不一致，覆盖后再钉死。
switch_compose_images "${TARGET_BACKEND_IMAGE}" "${TARGET_FRONTEND_IMAGE}"
ensure_image "${TARGET_BACKEND_IMAGE}"
ensure_image "${TARGET_FRONTEND_IMAGE}"
ensure_image "${IMAGE_OPENFGA}"

log "3) 停 API/worker，先起 mysql/redis/openfga"
docker stop "${FRONTEND_CONTAINER}" "${BACKEND_CONTAINER}" "${WORKER_CONTAINER}" 2>/dev/null || true
compose up -d mysql redis
wait_container "${MYSQL_CONTAINER}"
compose up -d openfga-migrate
log "等待 openfga-migrate"
docker wait bisheng-openfga-migrate || true
compose up -d openfga
wait_container bisheng-openfga

log "4) 用 sleep infinity 起 backend，拦住 entrypoint 抢跑 alembic upgrade head"
cat >"${HOP_OVERRIDE}" <<'YAML'
services:
  backend:
    entrypoint: ["/bin/sleep"]
    command: ["infinity"]
  backend_worker:
    entrypoint: ["/bin/sleep"]
    command: ["infinity"]
YAML
compose_hop up -d --no-deps backend
wait_container "${BACKEND_CONTAINER}"

log "5) Alembic 第一段 -> ${ALEMBIC_BEFORE_DEPT}"
docker exec -e PYTHONPATH=./ -w /app "${BACKEND_CONTAINER}" \
  bash -lc "alembic upgrade ${ALEMBIC_BEFORE_DEPT}"
cur="$(alembic_current)"
log "alembic current=${cur}"
[[ "${cur}" == "${ALEMBIC_BEFORE_DEPT}" ]] || die "第一段失败 current=${cur}"

log "6) create_all 补 department 等表（不要跑 init_default_data，会查尚未迁完的 role 列）"
docker exec -e PYTHONPATH=./ -w /app "${BACKEND_CONTAINER}" \
  bash -lc 'python - <<"PY"
import asyncio
from bisheng.core.database.tenant_filter import register_tenant_filter_events
from bisheng.core.database import get_database_connection

register_tenant_filter_events()

async def main():
    db = await get_database_connection()
    await db.create_db_and_tables()
    print("create_all ok")

asyncio.run(main())
PY'
table_exists department || die "create_all 后仍无 department"
table_exists user_department || die "create_all 后仍无 user_department"
log "department / user_department 已在"

log "7) 2.4 的 tag.business_type ENUM 装不下 tag_library，先改成 varchar"
if column_exists tag business_type; then
  mysql_exec "ALTER TABLE tag MODIFY business_type VARCHAR(64) NOT NULL DEFAULT 'APPLICATION'"
fi

log "8) Alembic 第二段 -> ${TARGET_ALEMBIC_HEAD}"
docker exec -e PYTHONPATH=./ -w /app "${BACKEND_CONTAINER}" \
  bash -lc 'alembic upgrade head'
cur="$(alembic_current)"
log "alembic current=${cur}"
[[ "${cur}" == "${TARGET_ALEMBIC_HEAD}" ]] || die "head 不是 ${TARGET_ALEMBIC_HEAD}，当前 ${cur}。禁止 stamp"
dbv="$(mysql_scalar "SELECT version_num FROM alembic_version")"
[[ "${dbv}" == "${TARGET_ALEMBIC_HEAD}" ]] || die "alembic_version=${dbv} 不匹配"

log "9) 去掉 hop override，按正常 entrypoint 拉起"
rm -f "${HOP_OVERRIDE}"
compose up -d backend backend_worker frontend
wait_container "${BACKEND_CONTAINER}"
wait_health

restart_logs="$(docker logs --since 3m "${BACKEND_CONTAINER}" 2>&1 || docker logs --tail 200 "${BACKEND_CONTAINER}" 2>&1 || true)"
if printf '%s\n' "${restart_logs}" | grep -q "WARNING: alembic migration failed"; then
  die "正常启动仍出现 alembic WARNING，不算成功"
fi
cur="$(alembic_current)"
[[ "${cur}" == "${TARGET_ALEMBIC_HEAD}" ]] || die "重启后 current=${cur}"

ledger "${STEP}" "OK" "alembic=${dbv}"
log "2.5.0-sg schema 完成。不要开 SG 同步。下一步："
log "  CONFIRM_F006=0 bash p2/31-f006-workstation.sh"
log "  CONFIRM_F006=1 bash p2/31-f006-workstation.sh"
