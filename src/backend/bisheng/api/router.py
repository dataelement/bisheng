# Router for base api
from bisheng.telemetry_search.api.router import router as telemetry_search_router
from fastapi import APIRouter

from bisheng.api.v1 import (assistant_router, audit_router, chat_router,
                            endpoints_router, evaluation_router,
                            group_router, mark_router,
                            report_router, tag_router,
                            user_router, variable_router, workflow_router,
                            workstation_router, tool_router, invite_code_router, skillcenter_router, flows_router)
from bisheng.channel.api.router import router as channel_router
from bisheng.chat_session.api.router import router as session_router
from bisheng.finetune.api.finetune import router as finetune_router
from bisheng.finetune.api.server import router as server_router
from bisheng.knowledge.api.router import qa_router, knowledge_router, knowledge_space_router
from bisheng.linsight.api.router import router as linsight_router
from bisheng.llm.api.router import router as llm_router
from bisheng.message.api.router import router as message_router
from bisheng.open_endpoints.api.endpoints.llm import router as llm_router_rpc
from bisheng.open_endpoints.api.router import (assistant_router_rpc, chat_router_rpc,
                                               knowledge_router_rpc, workflow_router_rpc,
                                               filelib_router_rpc)
from bisheng.department.api.router import router as department_router
from bisheng.user_group.api.router import router as user_group_router
from bisheng.permission.api.router import router as permission_router
from bisheng.role.api.router import router as role_router
from bisheng.share_link.api.router import router as share_link_router
from bisheng.org_sync.api.endpoints.relink import router as relink_router
from bisheng.org_sync.api.router import router as org_sync_router
from bisheng.sso_sync.api.router import router as sso_sync_router
from bisheng.tenant.api.router import router as tenant_router

router = APIRouter(prefix='/api/v1', )
router.include_router(chat_router)
router.include_router(endpoints_router)
router.include_router(knowledge_router)
router.include_router(knowledge_space_router)
router.include_router(server_router)
router.include_router(user_router)
router.include_router(qa_router)
router.include_router(variable_router)
router.include_router(report_router)
router.include_router(finetune_router)
router.include_router(assistant_router)
router.include_router(group_router)
router.include_router(audit_router)
router.include_router(evaluation_router)
router.include_router(tag_router)
router.include_router(llm_router)
router.include_router(workflow_router)
router.include_router(mark_router)
router.include_router(workstation_router)
router.include_router(skillcenter_router)
router.include_router(flows_router)
router.include_router(linsight_router)
router.include_router(tool_router)
router.include_router(invite_code_router)
router.include_router(session_router)
router.include_router(share_link_router)
router.include_router(telemetry_search_router)
router.include_router(channel_router)
router.include_router(message_router)
router.include_router(department_router)
router.include_router(user_group_router)
router.include_router(permission_router)
router.include_router(role_router)
router.include_router(org_sync_router)
router.include_router(sso_sync_router)
router.include_router(relink_router)
router.include_router(tenant_router)

router_rpc = APIRouter(prefix='/api/v2', )
router_rpc.include_router(knowledge_router_rpc)
router_rpc.include_router(filelib_router_rpc)
router_rpc.include_router(chat_router_rpc)
router_rpc.include_router(assistant_router_rpc)
router_rpc.include_router(workflow_router_rpc)
router_rpc.include_router(llm_router_rpc)
