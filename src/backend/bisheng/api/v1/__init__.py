from bisheng.api.v1.chat import router as chat_router
from bisheng.api.v1.endpoints import router as endpoints_router
from bisheng.api.v1.flows import router as flows_router
from bisheng.api.v1.knowledge import router as knowledge_router
from bisheng.api.v1.qa import router as qa_router
from bisheng.api.v1.report import router as report_router
from bisheng.api.v1.server import router as server_router
from bisheng.api.v1.skillcenter import router as skillcenter_router
from bisheng.api.v1.user import router as user_router
from bisheng.api.v1.validate import router as validate_router
from bisheng.api.v1.variable import router as variable_router

__all__ = [
    'chat_router',
    'endpoints_router',
    'validate_router',
    'flows_router',
    'skillcenter_router',
    'knowledge_router',
    'server_router',
    'user_router',
    'qa_router',
    'variable_router',
    'report_router',
]
