"""平台资源适配器的显式装配入口。"""

from typing import Literal, Protocol

from bisheng.common.errcode.flow import PlatformAgentDisabledError, PlatformAgentNotReadyError
from bisheng.core.config.settings import PlatformAgentConf
from bisheng.workflow.domain.schemas.platform_agent import (
    AgentInteraction,
    AgentInteractionReference,
    AgentInvokeResult,
    AgentReference,
    AgentRunObservation,
    AgentSubmissionReceipt,
    AgentVersion,
    VerifiedAgentActor,
)


class PlatformAgentProvider(Protocol):
    async def list_agents(
        self,
        actor: VerifiedAgentActor,
        cursor: str | None = None,
        *,
        page_size: int = 20,
        search: str | None = None,
    ) -> dict: ...

    async def get_version(self, actor: VerifiedAgentActor, ref: AgentReference) -> AgentVersion: ...

    async def check_use(self, actor: VerifiedAgentActor, ref: AgentReference) -> None: ...

    async def invoke(
        self, actor: VerifiedAgentActor, ref: AgentReference, inputs: dict, call_id: str
    ) -> AgentInvokeResult: ...


class LongTaskAgentProvider(PlatformAgentProvider, Protocol):
    async def start(self, actor, ref, inputs, call_id) -> AgentRunObservation: ...

    async def lookup_start(self, actor, ref, call_id) -> AgentRunObservation | None: ...

    async def get_status(self, actor, ref, run_id) -> AgentRunObservation: ...

    async def get_result(self, actor, ref, run_id) -> AgentInvokeResult | None: ...

    async def cancel(self, actor, ref, run_id, cancel_key) -> Literal["ACCEPTED", "TERMINAL", "REJECTED"]: ...


class InteractiveAgentProvider(LongTaskAgentProvider, Protocol):
    async def submit_interaction(
        self,
        actor: VerifiedAgentActor,
        ref: AgentReference,
        run_id: str,
        interaction: AgentInteraction,
        answer: str,
        submission_key: str,
    ) -> AgentSubmissionReceipt: ...

    async def lookup_submission(
        self,
        actor: VerifiedAgentActor,
        ref: AgentReference,
        run_id: str,
        interaction: AgentInteractionReference,
        submission_key: str,
    ) -> AgentSubmissionReceipt | None: ...


def build_provider(config: PlatformAgentConf, *, enable_interactions=False) -> PlatformAgentProvider:
    if config.mode == "disabled":
        raise PlatformAgentDisabledError()
    if config.mode == "real":
        if not config.resource_base_url.strip():
            raise PlatformAgentNotReadyError()
        from bisheng.workflow.domain.clients.platform_agent_real import RealPlatformAgentProvider

        return RealPlatformAgentProvider(config, enable_interactions=enable_interactions)
    from bisheng.workflow.domain.clients.platform_agent_mock import MockPlatformAgentProvider

    return MockPlatformAgentProvider(config, enable_interactions=enable_interactions)
