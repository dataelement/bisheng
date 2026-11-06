"""Pure, lazy source-disclosure graph; it does not register a process bootstrap."""

from bisheng.app_publish.application.reference_source_owner import HostedAppReferenceSourceOwner
from bisheng.assistant.application.reference_source_owner import AssistantReferenceSourceOwner
from bisheng.channel.application.reference_source_owner import ChannelReferenceSourceOwner
from bisheng.knowledge.application.reference_source_owner import KnowledgeReferenceSourceOwner
from bisheng.llm.application.model_default_read_identity import ModelDefaultReadIdentityPort
from bisheng.llm.application.model_default_source_owner import ModelDefaultSourceOwner
from bisheng.resource_reference.application.contracts import SourceType
from bisheng.resource_reference.application.source_disclosure import SourceDisclosureRuntime
from bisheng.workflow.application.reference_source_owner import WorkflowReferenceSourceOwner

_runtime: SourceDisclosureRuntime | None = None


def get_runtime() -> SourceDisclosureRuntime:
    global _runtime
    if _runtime is None:
        _runtime = SourceDisclosureRuntime(
            {
                SourceType.WORKFLOW_VERSION: WorkflowReferenceSourceOwner(),
                SourceType.ASSISTANT: AssistantReferenceSourceOwner(),
                SourceType.HOSTED_APP_VERSION: HostedAppReferenceSourceOwner(),
                SourceType.CHANNEL_SYNC: ChannelReferenceSourceOwner(),
                SourceType.KNOWLEDGE: KnowledgeReferenceSourceOwner(),
                SourceType.MODEL_DEFAULT: ModelDefaultSourceOwner(identity_port=ModelDefaultReadIdentityPort()),
            }
        )
    return _runtime
