#!/usr/bin/env bash
# 导出 B 业务 TSV + A 侧冲突检测用集合. 只读.
set -euo pipefail
STEP="p5.10-export"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"
mkdir -p "${LOG_DIR}/p5"
ledger "${STEP}" "START" ""

mysql_b_tsv "SELECT id,user_id,tenant_id,name,type,description,model,collection_name,index_name,state,is_released,is_favorite FROM knowledge" \
  > "${LOG_DIR}/p5/b-knowledge.tsv"
# 大字段走 JSON_OBJECT, 避免 TSV 碰到制表符/换行截断
mysql_b_jsonl "SELECT JSON_OBJECT('id',id,'user_id',user_id,'user_name',user_name,'knowledge_id',knowledge_id,'tenant_id',tenant_id,'file_name',file_name,'alias_name',alias_name,'file_type',file_type,'file_source',file_source,'object_name',object_name,'preview_file_object_name',preview_file_object_name,'bbox_object_name',bbox_object_name,'thumbnails',thumbnails,'status',status,'md5',md5,'file_size',file_size,'parse_type',parse_type,'split_rule',split_rule,'user_metadata',user_metadata,'remark',remark,'updater_id',updater_id,'original_uploader_id',original_uploader_id,'original_knowledge_id',original_knowledge_id) FROM knowledgefile" \
  > "${LOG_DIR}/p5/b-files.jsonl"
mysql_b_jsonl "SELECT JSON_OBJECT('id',id,'name',name,'user_id',user_id,'tenant_id',tenant_id,'description',description,'data',data,'logo',logo,'status',status,'flow_type',flow_type,'guide_word',guide_word) FROM flow" \
  > "${LOG_DIR}/p5/b-flows.jsonl"
mysql_b_jsonl "SELECT JSON_OBJECT('id',id,'flow_id',flow_id,'name',name,'data',data,'description',description,'user_id',user_id,'flow_type',flow_type,'is_current',is_current,'is_delete',is_delete,'original_version_id',original_version_id,'tenant_id',tenant_id) FROM flowversion" \
  > "${LOG_DIR}/p5/b-flowversions.jsonl"
mysql_b_tsv "SELECT id,flow_id,version_id,node_id,variable_name,value_type,is_option,value,tenant_id FROM t_variable_value" \
  > "${LOG_DIR}/p5/b-variables.tsv" || true
mysql_b_jsonl "SELECT JSON_OBJECT('id',id,'name',name,'tenant_id',tenant_id,'logo',logo,'desc',\`desc\`,'system_prompt',system_prompt,'prompt',prompt,'guide_word',guide_word,'guide_question',guide_question,'model_name',model_name,'temperature',temperature,'max_token',max_token,'status',status,'user_id',user_id,'is_delete',is_delete) FROM assistant" \
  > "${LOG_DIR}/p5/b-assistants.jsonl"
mysql_b_tsv "SELECT id,assistant_id,tool_id,flow_id,knowledge_id,tenant_id FROM assistantlink" \
  > "${LOG_DIR}/p5/b-assistantlinks.tsv"
mysql_b_jsonl "SELECT JSON_OBJECT('chat_id',chat_id,'name',name,'flow_id',flow_id,'flow_type',flow_type,'flow_name',flow_name,'flow_description',flow_description,'flow_logo',flow_logo,'user_id',user_id,'tenant_id',tenant_id,'group_ids',group_ids,'is_delete',is_delete,'like',\`like\`,'dislike',dislike,'copied',copied,'sensitive_status',sensitive_status) FROM message_session" \
  > "${LOG_DIR}/p5/b-sessions.jsonl"
mysql_b_jsonl "SELECT JSON_OBJECT('id',id,'is_bot',is_bot,'source',source,'mark_status',mark_status,'mark_user',mark_user,'mark_user_name',mark_user_name,'message',message,'extra',extra,'type',type,'category',category,'flow_id',flow_id,'chat_id',chat_id,'user_id',user_id,'tenant_id',tenant_id,'liked',liked,'solved',solved,'copied',copied,'sensitive_status',sensitive_status,'sender',sender,'receiver',receiver,'intermediate_steps',intermediate_steps,'files',files,'remark',remark,'create_time',DATE_FORMAT(create_time,'%Y-%m-%d %H:%i:%s')) FROM chatmessage" \
  > "${LOG_DIR}/p5/b-messages.jsonl"
mysql_b_tsv "SELECT user_id,type,type_detail FROM user_link" > "${LOG_DIR}/p5/b-user-links.tsv" || true
mysql_b_tsv "SELECT id,resource_id,resource_type,share_mode,status,create_user_id,tenant_id FROM share_link" > "${LOG_DIR}/p5/b-share-links.tsv" || true
mysql_b_jsonl "SELECT JSON_OBJECT('id',id,'user_id',user_id,'knowledge_id',knowledge_id,'questions',questions,'answers',answers,'source',source,'status',status,'extra_meta',extra_meta,'remark',remark,'tenant_id',tenant_id) FROM qaknowledge" \
  > "${LOG_DIR}/p5/b-qaknowledge.jsonl" || true
mysql_b_tsv "SELECT id,name,business_type,business_id,user_id,tenant_id,resource_type,is_deleted,review_status,reject_reason,reviewer_id,remark FROM review_tag" \
  > "${LOG_DIR}/p5/b-review-tag.tsv" || true
mysql_b_tsv "SELECT id,tag_id,resource_id,resource_type,user_id,tenant_id,is_deleted,remark FROM review_tag_link" \
  > "${LOG_DIR}/p5/b-review-tag-link.tsv" || true
mysql_b_tsv "SELECT id,group_id,third_id,type,tenant_id FROM groupresource" \
  > "${LOG_DIR}/p5/b-group-resource.tsv" || true
mysql_b_tsv "SELECT id,type,dict_key,dict_value,sort_order,is_enabled,tenant_id FROM system_dictionary" \
  > "${LOG_DIR}/p5/b-dictionary.tsv" || true
mysql_b_jsonl "SELECT JSON_OBJECT('id',id,'citation_id',citation_id,'message_id',message_id,'chat_id',chat_id,'flow_id',flow_id,'citation_type',citation_type,'source_payload',source_payload) FROM message_citation" \
  > "${LOG_DIR}/p5/b-citations.jsonl" || true
mysql_b_tsv "SELECT id,tenant_id,message_id,citation_id FROM message_citation_relation" \
  > "${LOG_DIR}/p5/b-citation-relations.tsv" || true
mysql_b_tsv "SELECT id,create_user,create_id,app_id,process_users,mark_user,status,tenant_id FROM marktask" \
  > "${LOG_DIR}/p5/b-mark-tasks.tsv" || true
mysql_b_tsv "SELECT id,create_user,flow_type,create_id,app_id,task_id,session_id,status,tenant_id FROM markrecord" \
  > "${LOG_DIR}/p5/b-mark-records.tsv" || true
mysql_b_tsv "SELECT id,app_id,user_id,task_id,create_id,status,tenant_id FROM markappuser" \
  > "${LOG_DIR}/p5/b-mark-app-users.tsv" || true
mysql_b_tsv "SELECT id,flow_id,file_name,template_name,version_key,newversion_key,object_name,del_yn,tenant_id FROM t_report" \
  > "${LOG_DIR}/p5/b-reports.tsv" || true
mysql_b_jsonl "SELECT JSON_OBJECT('id',id,'name',name,'logo',logo,'extra',extra,'description',description,'server_host',server_host,'auth_method',auth_method,'api_key',api_key,'auth_type',auth_type,'is_preset',is_preset,'user_id',user_id,'is_delete',is_delete,'tenant_id',tenant_id,'openapi_schema',openapi_schema) FROM t_gpts_tools_type" \
  > "${LOG_DIR}/p5/b-tool-types.jsonl" || true
chmod 600 "${LOG_DIR}/p5/b-tool-types.jsonl" || true
mysql_b_jsonl "SELECT JSON_OBJECT('id',id,'name',name,'logo',logo,'desc',\`desc\`,'tool_key',tool_key,'type',type,'is_preset',is_preset,'is_delete',is_delete,'extra',extra,'api_params',api_params,'user_id',user_id,'tenant_id',tenant_id) FROM t_gpts_tools" \
  > "${LOG_DIR}/p5/b-tools.jsonl" || true
chmod 600 "${LOG_DIR}/p5/b-tools.jsonl" || true
mysql_b_tsv "SELECT id,role_id,third_id,type,tenant_id FROM roleaccess" \
  > "${LOG_DIR}/p5/b-roleaccess.tsv" || true
mysql_b_tsv "SELECT user_id,role_id,tenant_id FROM userrole" \
  > "${LOG_DIR}/p5/b-userroles.tsv" || true
mysql_b_jsonl "SELECT JSON_OBJECT('id',id,'operator_id',operator_id,'operator_name',operator_name,'group_ids',group_ids,'system_id',system_id,'event_type',event_type,'object_type',object_type,'object_id',object_id,'object_name',object_name,'note',note,'ip_address',ip_address,'tenant_id',tenant_id,'operator_tenant_id',operator_tenant_id,'action',action,'target_type',target_type,'target_id',target_id,'reason',reason,'metadata',\`metadata\`,'create_time',DATE_FORMAT(create_time,'%Y-%m-%d %H:%i:%s'),'update_time',DATE_FORMAT(update_time,'%Y-%m-%d %H:%i:%s')) FROM auditlog" \
  > "${LOG_DIR}/p5/b-audit.jsonl" || true

{
  echo "metric	value"
  echo -n "b_knowledge_01	"; mysql_scalar "SELECT COUNT(*) FROM knowledge WHERE type IN (0,1)"
  echo -n "b_file_01	"; mysql_scalar "SELECT COUNT(*) FROM knowledgefile f JOIN knowledge k ON f.knowledge_id=k.id WHERE k.type IN (0,1)"
  echo -n "b_qa	"; mysql_scalar "SELECT COUNT(*) FROM qaknowledge q JOIN knowledge k ON q.knowledge_id=k.id WHERE k.type IN (0,1)" || echo 0
  echo -n "b_flow	"; mysql_scalar "SELECT COUNT(*) FROM flow"
  echo -n "b_assistant	"; mysql_scalar "SELECT COUNT(*) FROM assistant"
  echo -n "b_session	"; mysql_scalar "SELECT COUNT(*) FROM message_session"
  echo -n "b_message	"; mysql_scalar "SELECT COUNT(*) FROM chatmessage"
  echo -n "b_audit	"; mysql_scalar "SELECT COUNT(*) FROM auditlog" || echo 0
} | tee "${LOG_DIR}/p5/b-baseline.tsv"

mysql_a_tsv "SELECT id,name FROM knowledge" > "${LOG_DIR}/p5/a-knowledge.tsv"
mysql_a "SELECT id FROM knowledge WHERE type=3" > "${LOG_DIR}/p5/a-space-ids.txt"
mysql_a_tsv "SELECT id FROM flow" > "${LOG_DIR}/p5/a-flow-ids.tsv"
mysql_a_tsv "SELECT name FROM flow" > "${LOG_DIR}/p5/a-flow-names.tsv"
mysql_a_tsv "SELECT chat_id FROM message_session" > "${LOG_DIR}/p5/a-chat-ids.tsv"
mysql_a_tsv "SELECT id FROM chatmessage" > "${LOG_DIR}/p5/a-message-ids.tsv" || true
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM knowledge" > "${LOG_DIR}/p5/next-knowledge-id.txt"
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM knowledgefile" > "${LOG_DIR}/p5/next-file-id.txt"
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM flowversion" > "${LOG_DIR}/p5/next-version-id.txt"
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM chatmessage" > "${LOG_DIR}/p5/next-message-id.txt"
mysql_a_tsv "SELECT id FROM assistant" > "${LOG_DIR}/p5/a-assistant-ids.tsv"
mysql_a_tsv "SELECT id FROM qaknowledge" > "${LOG_DIR}/p5/a-qa-ids.tsv" || true
mysql_a_tsv "SELECT id FROM review_tag" > "${LOG_DIR}/p5/a-tag-ids.tsv" || true
mysql_a_tsv "SELECT id FROM review_tag_link" > "${LOG_DIR}/p5/a-tag-link-ids.tsv" || true
mysql_a_tsv "SELECT id FROM groupresource" > "${LOG_DIR}/p5/a-group-resource-ids.tsv" || true
mysql_a_tsv "SELECT id,type,dict_key,dict_value,tenant_id FROM system_dictionary" > "${LOG_DIR}/p5/a-dictionary.tsv" || true
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM qaknowledge" > "${LOG_DIR}/p5/next-qa-id.txt" || echo 1 > "${LOG_DIR}/p5/next-qa-id.txt"
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM review_tag" > "${LOG_DIR}/p5/next-tag-id.txt" || echo 1 > "${LOG_DIR}/p5/next-tag-id.txt"
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM review_tag_link" > "${LOG_DIR}/p5/next-tag-link-id.txt" || echo 1 > "${LOG_DIR}/p5/next-tag-link-id.txt"
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM groupresource" > "${LOG_DIR}/p5/next-group-resource-id.txt" || echo 1 > "${LOG_DIR}/p5/next-group-resource-id.txt"
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM system_dictionary" > "${LOG_DIR}/p5/next-dictionary-id.txt" || echo 1 > "${LOG_DIR}/p5/next-dictionary-id.txt"
mysql_a_tsv "SELECT id FROM message_citation" > "${LOG_DIR}/p5/a-citation-ids.tsv" || true
mysql_a_tsv "SELECT citation_id FROM message_citation" > "${LOG_DIR}/p5/a-citation-cids.tsv" || true
mysql_a_tsv "SELECT id FROM message_citation_relation" > "${LOG_DIR}/p5/a-citation-relation-ids.tsv" || true
mysql_a_tsv "SELECT id FROM marktask" > "${LOG_DIR}/p5/a-mark-task-ids.tsv" || true
mysql_a_tsv "SELECT id FROM markrecord" > "${LOG_DIR}/p5/a-mark-record-ids.tsv" || true
mysql_a_tsv "SELECT id FROM markappuser" > "${LOG_DIR}/p5/a-mark-app-user-ids.tsv" || true
mysql_a_tsv "SELECT id FROM t_report" > "${LOG_DIR}/p5/a-report-ids.tsv" || true
mysql_a_tsv "SELECT version_key FROM t_report WHERE version_key IS NOT NULL" > "${LOG_DIR}/p5/a-report-keys.tsv" || true
mysql_a_tsv "SELECT id FROM t_gpts_tools_type" > "${LOG_DIR}/p5/a-tool-type-ids.tsv" || true
mysql_a_tsv "SELECT name FROM t_gpts_tools_type" > "${LOG_DIR}/p5/a-tool-type-names.tsv" || true
mysql_a_tsv "SELECT id FROM t_gpts_tools" > "${LOG_DIR}/p5/a-tool-ids.tsv" || true
mysql_a_tsv "SELECT tool_key FROM t_gpts_tools WHERE tool_key IS NOT NULL AND tool_key<>''" > "${LOG_DIR}/p5/a-tool-keys.tsv" || true
mysql_a_tsv "SELECT id FROM roleaccess" > "${LOG_DIR}/p5/a-role-access-ids.tsv" || true
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM message_citation" > "${LOG_DIR}/p5/next-citation-id.txt" || echo 1 > "${LOG_DIR}/p5/next-citation-id.txt"
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM message_citation_relation" > "${LOG_DIR}/p5/next-citation-relation-id.txt" || echo 1 > "${LOG_DIR}/p5/next-citation-relation-id.txt"
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM marktask" > "${LOG_DIR}/p5/next-mark-task-id.txt" || echo 1 > "${LOG_DIR}/p5/next-mark-task-id.txt"
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM markrecord" > "${LOG_DIR}/p5/next-mark-record-id.txt" || echo 1 > "${LOG_DIR}/p5/next-mark-record-id.txt"
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM markappuser" > "${LOG_DIR}/p5/next-mark-app-user-id.txt" || echo 1 > "${LOG_DIR}/p5/next-mark-app-user-id.txt"
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM t_report" > "${LOG_DIR}/p5/next-report-id.txt" || echo 1 > "${LOG_DIR}/p5/next-report-id.txt"
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM t_gpts_tools_type" > "${LOG_DIR}/p5/next-tool-type-id.txt" || echo 1 > "${LOG_DIR}/p5/next-tool-type-id.txt"
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM t_gpts_tools" > "${LOG_DIR}/p5/next-tool-id.txt" || echo 1 > "${LOG_DIR}/p5/next-tool-id.txt"
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM roleaccess" > "${LOG_DIR}/p5/next-role-access-id.txt" || echo 1 > "${LOG_DIR}/p5/next-role-access-id.txt"
# 仅用于 UUID 冲突检测; 行数很大时会慢
mysql_a_tsv "SELECT id FROM auditlog" > "${LOG_DIR}/p5/a-audit-ids.tsv" || true
mysql_a_tsv "SELECT id,collection_name,index_name FROM knowledge WHERE type=3" \
  > "${LOG_DIR}/p5/a-space-stores.tsv" || true
mysql_a_tsv "SELECT id,type,collection_name,index_name FROM knowledge" \
  > "${LOG_DIR}/p5/a-knowledge-stores.tsv" || true
mysql_b_jsonl "SELECT JSON_OBJECT('id',id,'server_id',server_id,'name',name,'description',description,'model_name',model_name,'model_type',model_type,'config',config,'status',status,'remark',remark,'online',online,'user_id',user_id,'tenant_id',tenant_id) FROM llm_model" \
  > "${LOG_DIR}/p5/b-llm-models.jsonl" || true
chmod 600 "${LOG_DIR}/p5/b-llm-models.jsonl" || true
mysql_a_jsonl "SELECT JSON_OBJECT('id',id,'server_id',server_id,'model_name',model_name) FROM llm_model" \
  > "${LOG_DIR}/p5/a-llm-models.jsonl" || true
mysql_b_jsonl "SELECT JSON_OBJECT('id',id,'name',name,'description',description,'type',type,'config',config,'user_id',user_id,'tenant_id',tenant_id,'limit_flag',limit_flag,'limit',\`limit\`) FROM llm_server" \
  > "${LOG_DIR}/p5/b-llm-servers.jsonl" || true
chmod 600 "${LOG_DIR}/p5/b-llm-servers.jsonl" || true
mysql_a_tsv "SELECT id FROM llm_server" > "${LOG_DIR}/p5/a-llm-server-ids.tsv" || true
mysql_a_tsv "SELECT id FROM llm_model" > "${LOG_DIR}/p5/a-llm-model-ids.tsv" || true
mysql_a_tsv "SELECT name FROM llm_server" > "${LOG_DIR}/p5/a-llm-server-names.tsv" || true
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM llm_server" > "${LOG_DIR}/p5/next-llm-server-id.txt" || echo 1 > "${LOG_DIR}/p5/next-llm-server-id.txt"
mysql_a "SELECT COALESCE(MAX(id),0)+1 FROM llm_model" > "${LOG_DIR}/p5/next-llm-model-id.txt" || echo 1 > "${LOG_DIR}/p5/next-llm-model-id.txt"

bash "${PACK_ROOT}/p5/12-export-b-openfga.sh" || log "B OpenFGA 导出失败, 部门授权将只靠 roleaccess"

ledger "${STEP}" "OK" "${LOG_DIR}/p5"
echo "OK ${STEP}"
