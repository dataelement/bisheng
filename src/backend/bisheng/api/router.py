# Router for base api
from fastapi import APIRouter

from bisheng.api.v1 import (assistant_router, audit_router, chat_router, component_router,
                            endpoints_router, evaluation_router, flows_router,
                            group_router, mark_router,
                            report_router, skillcenter_router, tag_router,
                            user_router, validate_router, variable_router, workflow_router,
                            workstation_router, tool_router, invite_code_router)
from bisheng.chat_session.api.router import router as session_router
from bisheng.finetune.api.finetune import router as finetune_router
from bisheng.finetune.api.server import router as server_router
from bisheng.knowledge.api.router import qa_router, knowledge_router
from bisheng.llm.api.router import router as llm_router
from bisheng.open_endpoints.api.endpoints.llm import router as llm_router_rpc
from bisheng.open_endpoints.api.router import (assistant_router_rpc, chat_router_rpc, flow_router,
                                               knowledge_router_rpc, workflow_router_rpc,
                                               filelib_router_rpc)
from bisheng.share_link.api.router import router as share_link_router
from bisheng.linsight.api.router import router as linsight_router
from bisheng.telemetry_search.api.router import router as telemetry_search_router

router = APIRouter(prefix='/api/v1', )
router.include_router(chat_router)
router.include_router(endpoints_router)
router.include_router(validate_router)
router.include_router(flows_router)
router.include_router(skillcenter_router)
router.include_router(knowledge_router)
router.include_router(server_router)
router.include_router(user_router)
router.include_router(qa_router)
router.include_router(variable_router)
router.include_router(report_router)
router.include_router(finetune_router)
router.include_router(component_router)
router.include_router(assistant_router)
router.include_router(group_router)
router.include_router(audit_router)
router.include_router(evaluation_router)
router.include_router(tag_router)
router.include_router(llm_router)
router.include_router(workflow_router)
router.include_router(mark_router)
router.include_router(workstation_router)
router.include_router(linsight_router)
router.include_router(tool_router)
router.include_router(invite_code_router)
router.include_router(session_router)
router.include_router(share_link_router)
router.include_router(telemetry_search_router)

router_rpc = APIRouter(prefix='/api/v2', )
router_rpc.include_router(knowledge_router_rpc)
router_rpc.include_router(filelib_router_rpc)
router_rpc.include_router(chat_router_rpc)
router_rpc.include_router(flow_router)
router_rpc.include_router(assistant_router_rpc)
router_rpc.include_router(workflow_router_rpc)
router_rpc.include_router(llm_router_rpc)
