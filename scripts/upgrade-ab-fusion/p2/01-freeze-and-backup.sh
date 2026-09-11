#!/usr/bin/env bash
# 停写入并备份。MinIO/Milvus/ES 命令按现场存储改 BACKUP_DIR 下的子脚本。
set -euo pipefail
STEP="p2.01-backup"
# 默认值可被环境变量覆盖；compose 路径一律自动发现，不写死。
: "${BACKEND_CONTAINER:=bisheng-backend}"
: "${WORKER_CONTAINER:=bisheng-backend-worker}"
: "${FRONTEND_CONTAINER:=bisheng-frontend}"
: "${GATEWAY_CONTAINER:=bisheng-gateway}"
: "${MYSQL_CONTAINER:=bisheng-mysql}"
: "${MYSQL_DB:=bisheng}"
: "${BACKUP_DIR:=/data/upgrade-backups}"
: "${APPLY:=0}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
discover_deployment
preflight_report
ledger "${STEP}" "START" ""

stamp="$(date +%Y%m%d%H%M%S)"
dest="${BACKUP_DIR}/${stamp}"
mkdir -p "${dest}"

log "1) 停 API 写入：停 frontend / gateway / backend / worker / beat（保留 mysql/minio/milvus/es）"
if require_apply; then
  docker stop "${FRONTEND_CONTAINER}" "${GATEWAY_CONTAINER}" \
    "${BACKEND_CONTAINER}" "${WORKER_CONTAINER}" 2>/dev/null || true
  docker ps --format '{{.Names}} {{.Status}}' | tee "${dest}/containers-after-stop.txt"
fi

log "2) mysqldump"
if require_apply; then
  docker exec "${MYSQL_CONTAINER}" sh -c \
    'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines --triggers --databases '"${MYSQL_DB}" \
    >"${dest}/mysql-${MYSQL_DB}.sql"
  sha256_file "${dest}/mysql-${MYSQL_DB}.sql" >"${dest}/mysql-${MYSQL_DB}.sql.sha256"
fi

log "3) 复制 compose 与 config"
if require_apply; then
  # 现场可能叠加了多个 -f，逐个备份，不能只存第一个。
  for f in ${COMPOSE_CONFIG_FILES[@]+"${COMPOSE_CONFIG_FILES[@]}"}; do
    cp -a "${f}" "${dest}/$(basename "${f}")"
  done
  # backend 此时已停，docker exec 用不了；直接从挂载反查到的宿主机路径拷。
  resolve_host_file_optional "${BACKEND_CONTAINER}" cfg_host "${CONFIG_YAML_DESTS[@]}"
  if [[ -n "${cfg_host}" ]]; then
    cp -a "${cfg_host}" "${dest}/config.yaml"
  else
    log "config.yaml 非 bind mount 或未挂载，请手工拷到 ${dest}"
  fi
fi

cat >"${dest}/TODO-storage.txt" <<EOF
还需要同一冻结点的：
- MinIO 数据目录或 mc mirror
- Milvus 数据目录
- Elasticsearch 快照
- 镜像清单 docker image ls
备份文件存在不等于可回滚。P2 必须另做一次 restore 到隔离机并启动原 2.2 镜像。
EOF

ledger "${STEP}" "OK" "${dest}"
log "备份目录 ${dest}"
