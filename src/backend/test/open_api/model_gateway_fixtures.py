"""Shared doubles for the model protocol face tests (F051 T005).

Built once here so no individual test file invents its own fake model or its
own catalog rows — the point of the face is that three consumers agree on one
answer, and three private fakes would hide exactly the disagreement the tests
exist to catch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Depends, FastAPI
from langchain_core.messages import AIMessage, AIMessageChunk

from bisheng.open_api.api.dependencies import verify_open_api_access
from bisheng.open_api.api.endpoints.model_gateway import router as model_gateway_router
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from bisheng.open_api.domain.context import OpenApiPrincipal


def build_model_face_app() -> FastAPI:
    """A standalone app carrying exactly the v2 contract the real one does.

    ``bisheng.main.app`` evaluates ``open_platform.enabled`` at import time, so a
    test that flips the switch afterwards gets the mounting decision made before
    it ran. Building the router here is how both states are testable in one
    process.
    """

    app = FastAPI()
    register_open_api_exception_handlers(app)
    router = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_open_api_access)])
    router.include_router(model_gateway_router)
    app.include_router(router)
    return app


def service_account_principal(
    *,
    scopes: frozenset[str] = frozenset({"model:invoke"}),
    tenant_id: int = 9,
    credential_id: int = 7,
) -> OpenApiPrincipal:
    return OpenApiPrincipal(
        credential_id=credential_id,
        actor_kind="service_account",
        actor_id=31,
        actor_name="local-dev",
        tenant_id=tenant_id,
        resource_owner_user_id=12,
        scopes=scopes,
        authorization_subject_type="service_account",
        authorization_subject_id=31,
        effective_user_id=None,
    )


def hosted_app_principal(*, app_slug: str = "survey-app", tenant_id: int = 9) -> OpenApiPrincipal:
    """A hosted-application principal.

    ``model_construct`` because F055 T055 has not widened ``actor_kind``'s
    Literal yet; once it has, this becomes a normal construction and nothing
    else in these tests changes.
    """

    return OpenApiPrincipal.model_construct(
        credential_id=71,
        actor_kind="hosted_app",
        actor_id=5,
        actor_name=app_slug,
        tenant_id=tenant_id,
        resource_owner_user_id=12,
        scopes=frozenset({"model:invoke"}),
        mode="S",
        authorization_subject_type="service_account",
        authorization_subject_id=5,
        effective_user_id=None,
        on_behalf_of_user_id=None,
        end_user_id=None,
    )


# --- catalog rows ------------------------------------------------------------


def server_row(server_id: int, name: str, *, server_type: str = "openai", tenant_id: int = 9):
    return SimpleNamespace(id=server_id, name=name, type=server_type, tenant_id=tenant_id)


def model_row(
    model_id: int,
    server_id: int,
    model_name: str,
    *,
    model_type: str = "llm",
    online: bool = True,
):
    return SimpleNamespace(
        id=model_id,
        server_id=server_id,
        model_name=model_name,
        model_type=model_type,
        online=online,
    )


def install_catalog(monkeypatch, servers: list, models: list, *, fail_with: Exception | None = None) -> None:
    """Point the catalog at in-memory rows (or make the read fail)."""

    from bisheng.llm.domain.services import model_catalog
    from bisheng.llm.domain.services.llm import LLMService

    model_catalog.invalidate_catalog()

    async def collect(_leaf_id: int, *, strict: bool = False):
        if fail_with is not None:
            raise fail_with
        return servers

    async def fetch_models(_server_ids):
        return models

    monkeypatch.setattr(LLMService, "acollect_visible_servers", staticmethod(collect))
    monkeypatch.setattr(model_catalog.LLMDao, "aget_model_by_server_ids", staticmethod(fetch_models))


# --- fake model --------------------------------------------------------------


@dataclass
class FakeBishengLLM:
    """Scripted stand-in for ``BishengLLM`` with the surface the face uses."""

    stream_script: list[Any] = field(default_factory=list)
    invoke_result: Any = None
    raise_on_first_chunk: Exception | None = None
    raise_after: int | None = None
    raise_on_invoke: Exception | None = None
    bound: dict[str, Any] = field(default_factory=dict)
    init_kwargs: dict[str, Any] = field(default_factory=dict)
    seen_kwargs: dict[str, Any] = field(default_factory=dict)
    seen_messages: list = field(default_factory=list)

    def bind(self, **kwargs):
        self.bound = kwargs
        return self

    async def ainvoke(self, messages, **kwargs):
        self.seen_messages = messages
        self.seen_kwargs = kwargs
        if self.raise_on_invoke is not None:
            raise self.raise_on_invoke
        return self.invoke_result or AIMessage(content="ok")

    async def astream(self, messages, **kwargs):
        self.seen_messages = messages
        self.seen_kwargs = kwargs
        if self.raise_on_first_chunk is not None:
            raise self.raise_on_first_chunk
        for index, chunk in enumerate(self.stream_script):
            if self.raise_after is not None and index == self.raise_after:
                raise RuntimeError("upstream vanished mid-stream")
            yield chunk
        if self.raise_after is not None and self.raise_after >= len(self.stream_script):
            raise RuntimeError("upstream vanished mid-stream")


def install_fake_llm(monkeypatch, fake: FakeBishengLLM) -> FakeBishengLLM:
    from bisheng.llm.domain.services.llm import LLMService

    async def get_bisheng_llm(**kwargs):
        fake.init_kwargs = kwargs
        return fake

    monkeypatch.setattr(LLMService, "get_bisheng_llm", staticmethod(get_bisheng_llm))
    return fake


def text_chunk(text: str, **kwargs) -> AIMessageChunk:
    return AIMessageChunk(content=text, **kwargs)


def tool_chunk(*, name: str | None, args: str, call_id: str | None, index: int | None = None) -> AIMessageChunk:
    return AIMessageChunk(
        content="",
        tool_call_chunks=[{"name": name, "args": args, "id": call_id, "index": index, "type": "tool_call_chunk"}],
    )


def usage_chunk(*, prompt: int, completion: int, finish_reason: str = "stop") -> AIMessageChunk:
    return AIMessageChunk(
        content="",
        usage_metadata={
            "input_tokens": prompt,
            "output_tokens": completion,
            "total_tokens": prompt + completion,
        },
        response_metadata={"finish_reason": finish_reason},
    )


# --- record writer -----------------------------------------------------------


def capture_records(monkeypatch) -> list:
    """Collect enqueued ``ModelCallRecord`` rows instead of writing them."""

    from bisheng.open_api.domain.services import model_gateway_service

    rows: list = []
    monkeypatch.setattr(
        model_gateway_service,
        "model_call_record_writer",
        SimpleNamespace(enqueue=lambda row: rows.append(row) or True),
    )
    return rows


__all__ = [
    "FakeBishengLLM",
    "build_model_face_app",
    "capture_records",
    "hosted_app_principal",
    "install_catalog",
    "install_fake_llm",
    "model_row",
    "server_row",
    "service_account_principal",
    "text_chunk",
    "tool_chunk",
    "usage_chunk",
]
