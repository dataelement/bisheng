from bisheng.open_endpoints.api.endpoints.assistant import router as assistant_router_rpc
from bisheng.open_endpoints.api.endpoints.chat import router as chat_router_rpc
from bisheng.open_endpoints.api.endpoints.filelib import router as filelib_router_rpc
from bisheng.open_endpoints.api.endpoints.flow import router as flow_router
from bisheng.open_endpoints.api.endpoints.workflow import router as workflow_router_rpc
from .endpoints.knowledge import router as knowledge_router_rpc

__all__ = [
    'knowledge_router_rpc', 'chat_router_rpc', 'flow_router',
    'assistant_router_rpc', 'workflow_router_rpc', 'filelib_router_rpc'
]
