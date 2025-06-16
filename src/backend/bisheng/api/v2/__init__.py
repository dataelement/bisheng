from bisheng.api.v2.assistant import router as assistant_router_rpc
from bisheng.api.v2.chat import router as chat_router_rpc
from bisheng.api.v2.filelib import router as knowledge_router_rpc
from bisheng.api.v2.flow import router as flow_router
from bisheng.api.v2.rpc import router as rpc_router_rpc
from bisheng.api.v2.workflow import router as workflow_router_rpc
from bisheng.api.v2.workstation import router as workstation_router_rpc
from bisheng.api.v2.group import router as group_router_rpc

__all__ = [
    'knowledge_router_rpc', 'chat_router_rpc', 'rpc_router_rpc', 'flow_router',
    'assistant_router_rpc', 'workflow_router_rpc', 'workstation_router_rpc', 'group_router_rpc'
]
