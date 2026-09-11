#!/usr/bin/env bash
# 停写入并备份。MinIO/Milvus/ES 命令按现场存储改 BACKUP_DIR 下的子脚本。
set -euo pipefail
STEP="p2.01-backup"
# 测试机 B 10.168.24.121
COMPOSE_FILE="/data/bisheng-main/docker/docker-compose.yml"
BACKEND_CONTAINER="bisheng-backend"
MYSQL_CONTAINER="bisheng-mysql"
MYSQL_DB="bisheng"
BACKUP_DIR="/data/upgrade-backups"
APPLY=1
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
ledger "${STEP}" "START" ""

stamp="$(date +%Y%m%d%H%M%S)"
dest="${BACKUP_DIR}/${stamp}"
mkdir -p "${dest}"

log "1) 停 API 写入：停 frontend / gateway / backend / worker / beat（保留 mysql/minio/milvus/es）"
if require_apply; then
  docker stop bisheng-frontend bisheng-gateway bisheng-backend bisheng-backend-worker 2>/dev/null || true
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
  cp -a "${COMPOSE_FILE}" "${dest}/docker-compose.yml"
  docker exec "${BACKEND_CONTAINER}" sh -c 'cat /app/bisheng/config/config.yaml' >"${dest}/config.yaml" 2>/dev/null || \
    log "backend 已停，请从宿主机 volume 拷 config.yaml 到 ${dest}"
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
