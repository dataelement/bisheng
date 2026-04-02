from bisheng.api.v1.assistant import router as assistant_router
from bisheng.api.v1.audit import router as audit_router
from bisheng.api.v1.chat import router as chat_router
from bisheng.api.v1.endpoints import router as endpoints_router
from bisheng.api.v1.evaluation import router as evaluation_router
from bisheng.api.v1.flows import router as flows_router
from bisheng.api.v1.invite_code import router as invite_code_router
from bisheng.api.v1.mark_task import router as mark_router
from bisheng.api.v1.report import router as report_router
from bisheng.api.v1.skillcenter import router as skillcenter_router
from bisheng.api.v1.tag import router as tag_router
from bisheng.api.v1.usergroup import router as group_router
from bisheng.api.v1.variable import router as variable_router
from bisheng.api.v1.workflow import router as workflow_router
from bisheng.workstation.api import router as workstation_router
from bisheng.tool.api.tool import router as tool_router
from bisheng.user.api.user import router as user_router

__all__ = [
    'chat_router',
    'endpoints_router',
    'flows_router',
    'skillcenter_router',
    'user_router',
    'variable_router',
    'report_router',
    'assistant_router',
    'evaluation_router',
    'group_router',
    'audit_router',
    'tag_router',
    'workflow_router',
    'mark_router',
    "tool_router",
    "invite_code_router",
    "workstation_router",
]
