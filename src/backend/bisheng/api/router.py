# Router for base api
from bisheng.api.v1 import (assistant_router, audit_router, chat_router, component_router,
                            endpoints_router, evaluation_router, finetune_router, flows_router,
                            group_router, knowledge_router, llm_router, mark_router, qa_router,
                            report_router, server_router, skillcenter_router, tag_router,
                            user_router, validate_router, variable_router, workflow_router)
from bisheng.api.v2 import (assistant_router_rpc, chat_router_rpc, flow_router,
                            knowledge_router_rpc, rpc_router_rpc)
from fastapi import APIRouter

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

router_rpc = APIRouter(prefix='/api/v2', )
router_rpc.include_router(knowledge_router_rpc)
router_rpc.include_router(chat_router_rpc)
router_rpc.include_router(rpc_router_rpc)
router_rpc.include_router(flow_router)
router_rpc.include_router(assistant_router_rpc)
