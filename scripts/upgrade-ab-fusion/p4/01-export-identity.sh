#!/usr/bin/env bash
# 从 B(本地 mysql) 和 A(SSH) 导出身份 TSV. 只读.
set -euo pipefail
STEP="p4.01-export"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"
mkdir -p "${LOG_DIR}/p4"
ledger "${STEP}" "START" ""

mysql_b_tsv "SELECT user_id,user_name,email,phone_number,\`source\`,external_id,external_code,\`delete\` FROM \`user\`" \
  > "${LOG_DIR}/p4/b-users.tsv"
mysql_a_tsv "SELECT user_id,user_name,email,phone_number,\`source\`,external_id,external_code,\`delete\` FROM \`user\`" \
  > "${LOG_DIR}/p4/a-users.tsv"

mysql_b_tsv "SELECT id,dept_id,name,parent_id,external_id,source,is_deleted,tenant_id FROM department" \
  > "${LOG_DIR}/p4/b-depts.tsv" || true
mysql_a_tsv "SELECT id,dept_id,name,parent_id,external_id,source,is_deleted,tenant_id FROM department" \
  > "${LOG_DIR}/p4/a-depts.tsv" || true

mysql_b_tsv "SELECT id,role_name,role_type,tenant_id FROM role" > "${LOG_DIR}/p4/b-roles.tsv"
mysql_a_tsv "SELECT id,role_name,role_type,tenant_id FROM role" > "${LOG_DIR}/p4/a-roles.tsv"

mysql_b_tsv "SELECT id,group_name,remark,visibility,create_user,tenant_id FROM \`group\`" > "${LOG_DIR}/p4/b-groups.tsv"
mysql_a_tsv "SELECT id,group_name,tenant_id FROM \`group\`" > "${LOG_DIR}/p4/a-groups.tsv"

mysql_b_tsv "SELECT user_id,group_id,is_group_admin,tenant_id FROM usergroup" > "${LOG_DIR}/p4/b-usergroups.tsv"
mysql_b_tsv "SELECT user_id,department_id,is_primary,source FROM user_department" > "${LOG_DIR}/p4/b-user-departments.tsv" || true
mysql_b_tsv "SELECT user_id,role_id,tenant_id FROM userrole" > "${LOG_DIR}/p4/b-userroles.tsv"

mysql_b_tsv "SELECT id,tenant_code,tenant_name,status FROM tenant" > "${LOG_DIR}/p4/b-tenants.tsv"
mysql_a_tsv "SELECT id,tenant_code,tenant_name,status FROM tenant" > "${LOG_DIR}/p4/a-tenants.tsv"

mysql_b_tsv "SELECT m.id,m.model_name,s.type AS provider FROM llm_model m JOIN llm_server s ON m.server_id=s.id" \
  > "${LOG_DIR}/p4/b-models.tsv"
mysql_a_tsv "SELECT m.id,m.model_name,s.type AS provider FROM llm_model m JOIN llm_server s ON m.server_id=s.id" \
  > "${LOG_DIR}/p4/a-models.tsv"

mysql_b_tsv "SELECT id,name,type FROM llm_server" > "${LOG_DIR}/p4/b-servers.tsv"
mysql_a_tsv "SELECT id,name,type FROM llm_server" > "${LOG_DIR}/p4/a-servers.tsv"

mysql_b_tsv "SELECT id,name,tool_key,user_id,tenant_id FROM t_gpts_tools" > "${LOG_DIR}/p4/b-tools.tsv"
mysql_a_tsv "SELECT id,name,tool_key,user_id,tenant_id FROM t_gpts_tools" > "${LOG_DIR}/p4/a-tools.tsv"

ledger "${STEP}" "OK" "${LOG_DIR}/p4"
echo "OK ${STEP} -> ${LOG_DIR}/p4"
