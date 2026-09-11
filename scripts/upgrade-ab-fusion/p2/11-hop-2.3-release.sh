#!/usr/bin/env bash
# 2.3 release：角色菜单 + 遥测重建。跳过无 SQL 的 beta2/3/4。
set -euo pipefail
STEP="p2.11-2.3-release"
# 默认值可被环境变量覆盖；compose 路径一律自动发现，不写死。
: "${IMAGE_2_3:=dataelement/bisheng-backend:v2.3.0}"
: "${IMAGE_FRONTEND_2_3:=dataelement/bisheng-frontend:v2.3.0}"
: "${BACKEND_CONTAINER:=bisheng-backend}"
: "${MYSQL_CONTAINER:=bisheng-mysql}"
: "${MYSQL_DB:=bisheng}"
: "${APPLY:=0}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
discover_deployment
ledger "${STEP}" "START" ""

if require_apply; then
  mysql_file "$(dirname "$0")/sql/11-2.3-release-roleaccess.sql"
  switch_compose_images "${IMAGE_2_3}" "${IMAGE_FRONTEND_2_3}"
  compose up -d backend backend_worker frontend

  # 官方 reindex 在索引不存在时会 DELETE 404. 先补齐或给 v1 建别名.
  ensure_out="$(
    docker exec -i -e PYTHONPATH=./ "${BACKEND_CONTAINER}" bash -lc 'cd /app && python -' \
      <"$(dirname "$0")/ensure-telemetry-index.py"
  )"
  printf '%s\n' "${ensure_out}"
  if printf '%s\n' "${ensure_out}" | grep -q '^NEED_REINDEX=1$'; then
    docker exec -e PYTHONPATH=./ "${BACKEND_CONTAINER}" bash -lc \
      'if [ -f bisheng/script/base_telemetry_events_reindex.py ]; then python bisheng/script/base_telemetry_events_reindex.py;
       elif [ -f scripts/base_telemetry_events_reindex.py ]; then python scripts/base_telemetry_events_reindex.py;
       else echo "base_telemetry_events_reindex.py missing"; exit 1; fi' \
      || {
        log "官方 reindex 失败, 再补一次别名(空环境常见)"
        docker exec -i -e PYTHONPATH=./ "${BACKEND_CONTAINER}" bash -lc 'cd /app && python -' \
          <"$(dirname "$0")/ensure-telemetry-index.py" >/dev/null
      }
  else
    log "跳过官方 reindex: 无旧埋点索引或已有别名"
  fi
  docker exec -e PYTHONPATH=./ "${BACKEND_CONTAINER}" bash -lc \
    'cd /app && python -c "from bisheng.core.search.elasticsearch.manager import get_statistics_es_connection_sync as g; assert g().indices.exists(index=\"base_telemetry_events\"), \"base_telemetry_events missing\""'

  docker exec -e PYTHONPATH=./ "${BACKEND_CONTAINER}" bash -lc \
    'if [ -f bisheng/script/mid_table.sh ]; then sh bisheng/script/mid_table.sh;
     elif [ -f scripts/mid_table.sh ]; then sh scripts/mid_table.sh;
     else echo "mid_table.sh missing"; exit 1; fi'
  ledger "${STEP}" "OK" "roleaccess+telemetry"
else
  ledger "${STEP}" "DRY" "APPLY=0"
fi
log "下一步 20-hop-2.4-beta1.sh"
