# Router for base api
from bisheng.api.v1 import (chat_router, endpoints_router, flows_router, knowledge_router,
                            qa_router, report_router, server_router, skillcenter_router,
                            user_router, validate_router, variable_router)
from bisheng.api.v2 import chat_router_rpc, knowledge_router_rpc, rpc_router_rpc
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

router_rpc = APIRouter(prefix='/api/v2', )
router_rpc.include_router(knowledge_router_rpc)
router_rpc.include_router(chat_router_rpc)
router_rpc.include_router(rpc_router_rpc)
