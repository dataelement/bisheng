#!/usr/bin/env bash
# 2.5.0-sg：OpenFGA 库 + 钉死镜像 + Alembic 到 TARGET_ALEMBIC_HEAD。
# 禁止 stamp head。禁止把 entrypoint 的 WARNING-continue 当成功。
set -euo pipefail
STEP="p2.30-2.5"
# 测试机 B。升 2.5.0-sg 前改 TARGET_* / IMAGE_OPENFGA。
DRILL=1
TARGET_BACKEND_IMAGE="dataelement/bisheng-backend:v2.4.0"
TARGET_FRONTEND_IMAGE="dataelement/bisheng-frontend:v2.4.0"
TARGET_ALEMBIC_HEAD="unused-until-2.5"
IMAGE_OPENFGA="unused-until-2.5"
COMPOSE_FILE="/data/bisheng-main/docker/docker-compose.yml"
BACKEND_CONTAINER="bisheng-backend"
MYSQL_CONTAINER="bisheng-mysql"
MYSQL_DB="bisheng"
APPLY=1
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
ledger "${STEP}" "START" "head=${TARGET_ALEMBIC_HEAD}"
if [[ "${DRILL:-0}" != "1" ]]; then
  assert_pinned_image "${TARGET_BACKEND_IMAGE}"
  assert_pinned_image "${TARGET_FRONTEND_IMAGE}"
fi

if require_apply; then
  docker exec -i "${MYSQL_CONTAINER}" sh -c \
    'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --default-character-set=utf8mb4 -e "CREATE DATABASE IF NOT EXISTS openfga DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"'
  switch_compose_images "${TARGET_BACKEND_IMAGE}" "${TARGET_FRONTEND_IMAGE}"
  log "确认 compose 已含 openfga / openfga-migrate，且镜像=${IMAGE_OPENFGA}"
  grep -q openfga "${COMPOSE_FILE}" || die "compose 缺少 openfga：先改本脚本 IMAGE_OPENFGA 再跑 ensure-openfga.sh"

  compose up -d mysql openfga-migrate
  log "等待 openfga-migrate 结束"
  docker wait bisheng-openfga-migrate || true
  compose up -d openfga backend backend_worker frontend

  log "独立执行 alembic（失败即停）"
  docker exec -e PYTHONPATH=./ "${BACKEND_CONTAINER}" bash -lc 'alembic upgrade head'
  cur="$(docker exec -e PYTHONPATH=./ "${BACKEND_CONTAINER}" bash -lc 'alembic current' | tail -n 1 | awk '{print $1}')"
  log "alembic current=${cur}"
  [[ "${cur}" == "${TARGET_ALEMBIC_HEAD}" ]] || die "alembic current=${cur} 不等于 TARGET_ALEMBIC_HEAD=${TARGET_ALEMBIC_HEAD}"

  if docker logs "${BACKEND_CONTAINER}" 2>&1 | grep -q "WARNING: alembic migration failed"; then
    die "entrypoint 出现 alembic WARNING，按评审稿不算成功"
  fi

  dbv="$(mysql_scalar "SELECT version_num FROM alembic_version")"
  [[ "${dbv}" == "${TARGET_ALEMBIC_HEAD}" ]] || die "alembic_version=${dbv} 不匹配"

  ledger "${STEP}" "OK" "alembic=${dbv}"
else
  ledger "${STEP}" "DRY" "APPLY=0"
fi
log "本步不要启用 SG 同步。下一步 31-f006-workstation.sh"
log "不要把 A 的 OpenFGA store 拷过来。"
