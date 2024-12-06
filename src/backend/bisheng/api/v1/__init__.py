from bisheng.api.v1.assistant import router as assistant_router
from bisheng.api.v1.audit import router as audit_router
from bisheng.api.v1.chat import router as chat_router
from bisheng.api.v1.component import router as component_router
from bisheng.api.v1.endpoints import router as endpoints_router
from bisheng.api.v1.evaluation import router as evaluation_router
from bisheng.api.v1.finetune import router as finetune_router
from bisheng.api.v1.flows import router as flows_router
from bisheng.api.v1.knowledge import router as knowledge_router
from bisheng.api.v1.llm import router as llm_router
from bisheng.api.v1.mark_task import router as mark_router
from bisheng.api.v1.qa import router as qa_router
from bisheng.api.v1.report import router as report_router
from bisheng.api.v1.server import router as server_router
from bisheng.api.v1.skillcenter import router as skillcenter_router
from bisheng.api.v1.tag import router as tag_router
from bisheng.api.v1.user import router as user_router
from bisheng.api.v1.usergroup import router as group_router
from bisheng.api.v1.validate import router as validate_router
from bisheng.api.v1.variable import router as variable_router
from bisheng.api.v1.workflow import router as workflow_router

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
    'finetune_router',
    'component_router',
    'assistant_router',
    'evaluation_router',
    'group_router',
    'audit_router',
    'tag_router',
    'llm_router',
    'workflow_router',
    'mark_router',
]
