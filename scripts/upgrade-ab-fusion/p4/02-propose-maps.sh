#!/usr/bin/env bash
# 生成映射候选. conflict 非空则退出 2.
set -euo pipefail
STEP="p4.02-propose"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
mkdir -p "${LOG_DIR}/p4"
cd "${PACK_ROOT}"
ec=0
python3 fusion/cli.py users-propose "${LOG_DIR}/p4/a-users.tsv" "${LOG_DIR}/p4/b-users.tsv" --out-dir "${LOG_DIR}/p4" || ec=$?
python3 fusion/cli.py depts-propose "${LOG_DIR}/p4/a-depts.tsv" "${LOG_DIR}/p4/b-depts.tsv" --out-dir "${LOG_DIR}/p4" || ec=$?
python3 fusion/cli.py roles-propose "${LOG_DIR}/p4/a-roles.tsv" "${LOG_DIR}/p4/b-roles.tsv" --out-dir "${LOG_DIR}/p4" || ec=$?
python3 fusion/cli.py models-propose "${LOG_DIR}/p4/a-models.tsv" "${LOG_DIR}/p4/b-models.tsv" --out-dir "${LOG_DIR}/p4" || ec=$?
python3 fusion/cli.py servers-propose "${LOG_DIR}/p4/a-servers.tsv" "${LOG_DIR}/p4/b-servers.tsv" --out-dir "${LOG_DIR}/p4" || ec=$?
python3 fusion/cli.py tools-propose "${LOG_DIR}/p4/a-tools.tsv" "${LOG_DIR}/p4/b-tools.tsv" --out-dir "${LOG_DIR}/p4" || ec=$?
echo "把 logs/p4/*.proposed.csv 复核后复制到 p4/*.csv (user-map/dept-map/role-map/model-map/server-map/tool-map/tenant-map)"
echo "OK ${STEP}"
exit "${ec}"
