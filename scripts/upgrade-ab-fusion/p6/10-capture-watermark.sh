#!/usr/bin/env bash
# 抓 B 表级水位. LABEL=start|freeze|current
set -euo pipefail
STEP="p6.10-watermark"
LABEL="${LABEL:-current}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"

case "${LABEL}" in
  start|freeze|current) ;;
  *) die "LABEL 必须是 start|freeze|current" ;;
esac

out="${LOG_DIR}/p6/${LABEL}"
mkdir -p "${out}"
printf 'table\tentity\tcount\tmax_id\tmax_update_ts\n' > "${out}/summary.tsv"

while IFS=$'\t' read -r table entity id_sql sum_sql; do
  [[ -z "${table}" ]] && continue
  mysql_b_tsv "${id_sql}" > "${out}/${table}-ids.tsv" || true
  mysql_b_tsv "${sum_sql}" | awk 'NR>1' >> "${out}/summary.tsv" || true
done < <(
  python3 - "${PACK_ROOT}" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from fusion.watermark import WATERMARK_TABLES, id_select_sql, summary_select_sql
for table, entity in WATERMARK_TABLES:
    print("\t".join([table, entity, id_select_sql(table), summary_select_sql(table, entity)]))
PY
)

ledger "${STEP}" "OK" "LABEL=${LABEL} dir=${out}"
echo "OK ${STEP} LABEL=${LABEL} -> ${out}"
