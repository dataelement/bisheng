"""昆联平台大模型目录查询与推理编排服务。"""

from __future__ import annotations

from uuid import uuid4

from bisheng.common.errcode.flow import (
    PlatformLLMConfigurationError,
    PlatformLLMError,
    PlatformLLMNotReadyError,
    PlatformLLMPermissionError,
    PlatformLLMTokenError,
    PlatformLLMUpstreamError,
)
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError, KunlianError
from bisheng.core.config.settings import PlatformLLMConf
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.sso_sync.application.kunlian import resolve_kunlian_token_exchange_material
from bisheng.user.application.runtime_identity import read_current_person_facts
from bisheng.workflow.domain.clients.platform_llm import (
    SCOPE_MODEL_INVOKE,
    SCOPE_RESOURCES_READ,
    KunlianPlatformLLMClient,
)
from bisheng.workflow.domain.repositories.platform_agent import PlatformAgentRepository


def _session_reference_from_user(login_user) -> str | None:
    ref = getattr(login_user, "_runtime_credential_reference", None)
    if isinstance(ref, dict) and ref.get("kind") == "kunlian_session":
        value = ref.get("reference")
        if isinstance(value, str) and value:
            return value
    return None


def _map_kunlian_identity_error(exc: Exception) -> PlatformLLMError:
    if isinstance(exc, PlatformLLMError):
        return exc
    if isinstance(exc, KunlianDependencyUnavailableError):
        return PlatformLLMNotReadyError()
    if isinstance(exc, KunlianError):
        return PlatformLLMTokenError()
    if isinstance(exc, UnAuthorizedError):
        return PlatformLLMPermissionError()
    return PlatformLLMUpstreamError()


class PlatformLLMService:
    def __init__(
        self,
        *,
        config: PlatformLLMConf,
        repository=None,
        client: KunlianPlatformLLMClient | None = None,
        identity_reader=None,
        token_material_resolver=None,
    ):
        self.config = config
        self.repository = repository or PlatformAgentRepository()
        self._client = client
        self.identity_reader = identity_reader or read_current_person_facts
        self.token_material_resolver = token_material_resolver or resolve_kunlian_token_exchange_material

    @property
    def client(self) -> KunlianPlatformLLMClient:
        return self._client or KunlianPlatformLLMClient(self.config)

    async def authorize(self, login_user, workflow_id: str, action: str = "edit") -> None:
        flow = self.repository.get_workflow(workflow_id)
        if flow["tenant_id"] != login_user.tenant_id or flow.get("flow_type", 10) != 10:
            raise UnAuthorizedError()
        facts = (await self.identity_reader([login_user.user_id])).get(login_user.user_id, {})
        if facts.get("state") != "active" or facts.get("tenant_id") != login_user.tenant_id:
            raise UnAuthorizedError()
        await require_business_action(login_user, resource_type="workflow", resource_id=workflow_id, action=action)

    async def _exchange_for_user(
        self,
        user_id: int,
        *,
        scope: str,
        session_reference: str | None = None,
        trace_id: str | None = None,
    ):
        try:
            material = await self.token_material_resolver(
                user_id,
                session_reference=session_reference,
                oidc_token_url=self.config.oidc_token_url,
            )
            return await self.client.exchange_resource_token(
                oidc_token_url=material.oidc_token_url,
                client_id=material.client_id,
                client_secret=material.client_secret,
                subject_token=material.subject_token,
                scope=scope,
                trace_id=trace_id,
            )
        except Exception as exc:
            raise _map_kunlian_identity_error(exc) from None

    async def list_models(
        self,
        login_user,
        workflow_id: str,
        *,
        page_size: int = 20,
        search: str | None = None,
        cursor: str | None = None,
    ) -> dict:
        await self.authorize(login_user, workflow_id, action="edit")
        trace_id = uuid4().hex
        exchanged = await self._exchange_for_user(
            int(login_user.user_id),
            scope=SCOPE_RESOURCES_READ,
            session_reference=_session_reference_from_user(login_user),
            trace_id=trace_id,
        )
        page = await self.client.list_models(
            exchanged.access_token,
            page_size=page_size,
            search=search,
            cursor=cursor,
            trace_id=trace_id,
        )
        return {
            "items": [item.model_dump() for item in page.items],
            "page_size": page.page_size,
            "has_more": page.has_more,
            "next_cursor": page.next_cursor,
        }

    async def get_model_version(
        self,
        login_user,
        workflow_id: str,
        *,
        resource_id: str,
        version_id: str,
    ) -> dict:
        await self.authorize(login_user, workflow_id, action="edit")
        trace_id = uuid4().hex
        exchanged = await self._exchange_for_user(
            int(login_user.user_id),
            scope=SCOPE_RESOURCES_READ,
            session_reference=_session_reference_from_user(login_user),
            trace_id=trace_id,
        )
        return await self.client.get_model_version(
            exchanged.access_token,
            resource_id=resource_id,
            version_id=version_id,
            trace_id=trace_id,
        )

    async def invoke_chat(
        self,
        user_id: int,
        *,
        call_id: str,
        messages: list[dict],
        workflow_run_id: str | None = None,
        node_run_id: str | None = None,
        session_reference: str | None = None,
        trace_id: str | None = None,
    ):
        if not call_id or call_id.strip().lower() == "latest":
            raise PlatformLLMConfigurationError()
        req_trace = trace_id or uuid4().hex
        exchanged = await self._exchange_for_user(
            int(user_id),
            scope=SCOPE_MODEL_INVOKE,
            session_reference=session_reference,
            trace_id=req_trace,
        )
        return await self.client.chat_completions(
            exchanged.access_token,
            call_id=call_id,
            messages=messages,
            workflow_run_id=workflow_run_id,
            node_run_id=node_run_id,
            trace_id=req_trace,
        )
