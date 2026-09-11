#!/usr/bin/env bash
# compose 没有 openfga 时追加官方片段。密码从正在跑的 mysql 容器读取。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
# 测试机 B。升 2.5 前改 IMAGE_OPENFGA。
COMPOSE_FILE="/data/bisheng-main/docker/docker-compose.yml"
MYSQL_CONTAINER="bisheng-mysql"
IMAGE_OPENFGA="unused-until-2.5"
# shellcheck disable=SC1091
source "${ROOT}/lib/common.sh"
load_env

if grep -q "container_name: bisheng-openfga" "${COMPOSE_FILE}"; then
  log "compose 已有 openfga，跳过"
  exit 0
fi

pwd_mysql="$(docker exec "${MYSQL_CONTAINER}" printenv MYSQL_ROOT_PASSWORD)"
[[ -n "${pwd_mysql}" ]] || die "读不到 MYSQL_ROOT_PASSWORD"

cp -a "${COMPOSE_FILE}" "${COMPOSE_FILE}.bak.openfga.$(date +%Y%m%d%H%M%S)"
python3 - "${COMPOSE_FILE}" "${IMAGE_OPENFGA}" "${pwd_mysql}" <<'PY'
from pathlib import Path
import sys
path, image, password = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
uri = f"root:{password}@tcp(mysql:3306)/openfga?parseTime=true"
block = f'''
  openfga-migrate:
    container_name: bisheng-openfga-migrate
    image: {image}
    command: migrate
    environment:
      OPENFGA_DATASTORE_ENGINE: mysql
      OPENFGA_DATASTORE_URI: "{uri}"
    depends_on:
      mysql:
        condition: service_healthy
  openfga:
    container_name: bisheng-openfga
    image: {image}
    command: run
    environment:
      OPENFGA_DATASTORE_ENGINE: mysql
      OPENFGA_DATASTORE_URI: "{uri}"
      OPENFGA_LOG_FORMAT: json
      OPENFGA_PLAYGROUND_ENABLED: "false"
    ports:
      - "8080:8080"
    depends_on:
      openfga-migrate:
        condition: service_completed_successfully
    restart: unless-stopped
'''
text = path.read_text(encoding="utf-8")
# 插在 services: 后第一层
if "\nservices:\n" not in text and not text.startswith("services:"):
    raise SystemExit("compose 找不到 services:")
path.write_text(text.rstrip() + "\n" + block, encoding="utf-8")
print("appended openfga services")
PY
log "已追加 openfga。backend 的 depends_on 如缺 openfga，启动 2.5 时再补。"
