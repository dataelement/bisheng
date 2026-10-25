"""Isolated real audit HTTP chain. Synthetic identity/model/billing, never production auth."""

import asyncio
import resource
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import RLock
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, AIMessageChunk
from sqlmodel import SQLModel

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.dsh.api.dependencies import get_runtime
from bisheng.dsh.api.endpoints import model_audit_admin, models
from bisheng.dsh.audit_admin_runtime import ModelAuditAdministration
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository
from bisheng.dsh.domain.repositories.model_audit_setting import DshModelAuditSettingRepository
from bisheng.dsh.domain.repositories.model_audit_write import DshModelAuditWriteRepository
from bisheng.dsh.domain.schemas.chat import ChatCapabilities
from bisheng.dsh.domain.schemas.model_audit_context import AUDIT_FIELDS, AuditContext
from bisheng.dsh.domain.services.access import DshPrincipal
from bisheng.dsh.domain.services.model import DshModelService
from bisheng.dsh.domain.services.model_audit_body_access import DshModelAuditBodyAccessService
from bisheng.dsh.domain.services.model_audit_capture import AuditCapture
from bisheng.dsh.domain.services.model_audit_queries import DshModelAuditQueryService
from bisheng.dsh.domain.services.model_audit_setting import DshModelAuditSettingService
from bisheng.dsh.domain.services.model_audit_writer import DshModelAuditWriter
from bisheng.dsh.infrastructure.model_audit_blocking import run_audit_blocking
from bisheng.dsh.infrastructure.model_audit_queue import BoundedAuditQueue
from test.dsh.model_audit_fixtures import audit_session


class AuditHarness:
    def __init__(self, engine, storage, *, tokens, activity=None):
        self.engine, self.storage, self.tokens, self.activity = engine, storage, tokens, activity
        self.lock = RLock()
        SQLModel.metadata.create_all(engine, tables=[DshModelCall.__table__])
        from bisheng.core.database import tenant_filter

        tenant_filter._tenant_aware_tables.add(DshModelCall.__tablename__)
        self.writer = DshModelAuditWriter(lambda: self.scope(DshModelAuditWriteRepository), lambda: storage, attempts=2)
        self.queue = BoundedAuditQueue(
            max_events=4096,
            max_bytes=16 * 1024 * 1024,
            consumer=self.writer.write,
            body_consumer=self.writer.write_body_batch,
        )
        self.evidence = BoundedAuditQueue(max_events=4096, max_bytes=4 * 1024 * 1024, consumer=self.writer.write)
        self.annotations = BoundedAuditQueue(max_events=64, max_bytes=768 * 1024, consumer=self.writer.write)
        self.modes = DshModelAuditSettingService(
            self.read_mode,
            timeout_seconds=0.2,
            authorize_admin=self.authorize,
            repository_scope=lambda: self.scope(DshModelAuditSettingRepository),
            content_readiness=lambda: len(storage.keys.resolve(storage.keys.active_id)) == 32,
        )
        self.queries = DshModelAuditQueryService(self.authorize, lambda: self.scope(DshModelAuditQueryRepository))
        self.admin = ModelAuditAdministration(
            self.queries, DshModelAuditBodyAccessService(self.queries, lambda: storage), self.modes
        )
        self.calls = 0
        self.billing_failure = False
        self.model_failure = False
        self.policy = SimpleNamespace(
            allowed_model_ids=[42],
            quota_epoch=1,
            rows=[SimpleNamespace(model_id=42, version=1, quota_sync_state="READY", monthly_token_limit=100000)],
        )
        self.model = SimpleNamespace(
            id=42, model_name="audit-fixture", name="audit-fixture", config={}, create_time=datetime.now(UTC)
        )
        self.server = SimpleNamespace(name="Synthetic", type="openai")
        self.service = DshModelService(
            policy_reader=self.read_policy,
            model_loader=self.load_model,
            llm_builder=lambda *args: self,
            capabilities_for=lambda *args: ChatCapabilities(
                streaming=True, tools=True, vision=True, reasoning_content=True
            ),
            usage=self,
            now=lambda: datetime.now(UTC),
            audit_factory=self.capture,
        )
        self.app = self.build_app()

    @contextmanager
    def scope(self, repository_type):
        with self.lock, audit_session(self.engine, get_current_tenant_id() or 2) as session, session.begin():
            yield repository_type(session)

    async def read_mode(self):
        def read():
            with self.scope(DshModelAuditSettingRepository) as repository:
                return repository.read()

        return await run_audit_blocking(read)

    async def capture(self, principal, request, request_id, started, model, server, context):
        mode = await self.modes.read_effective()
        context = context or AuditContext()
        return AuditCapture(
            {
                "request_id": request_id,
                "tenant_id": int(principal.tenant_id),
                "user_id": int(principal.user_id),
                "session_id": principal.session_id,
                "model_id": model.id,
                "model_name": "Synthetic / audit-fixture",
                "provider_name": "Synthetic",
                "conversation_id": context.conversation_id,
                "request_kind": context.request_kind,
                "session_origin": context.session_origin,
                "parent_conversation_id": context.parent_conversation_id,
                "context_invalid": context.invalid,
                "effective_mode": mode.mode,
                "started_at": started,
                "input_units": len(request.messages) + 1,
            },
            self.queue,
            now=lambda: datetime.now(UTC),
            chunk_bytes=self.storage.max_block_bytes,
            request_budget_bytes=16 * 1024 * 1024,
            evidence_queue=self.evidence,
            activity=self.activity,
            digest_key=self.storage.keys.resolve(self.storage.keys.active_id),
            key_version=self.storage.keys.active_id,
            annotation_queue=self.annotations,
            message_sources=context.message_sources,
            message_sources_status=context.message_sources_status,
        )

    async def authorize(self, actor_id, tenant_id):
        if actor_id not in {1, 2} or (actor_id == 2 and tenant_id not in {None, 2}):
            raise HTTPException(403, "Synthetic administrator scope rejected")
        return {"scope": "instance" if actor_id == 1 else "tenant", "tenant_id": "2"}, tenant_id or 2

    async def read_policy(self, _user_id):
        return self.policy

    async def load_model(self, _model_id):
        return self.model, self.server

    async def check_and_start(self, event, **_kwargs):
        await self.persist_usage(event)
        return event

    async def record_usage(self, event, _version):
        if self.billing_failure:
            raise TimeoutError("Synthetic settlement unavailable")
        await self.persist_usage(event)

    async def get_request(self, _event):
        return None

    async def persist_usage(self, event):
        def write():
            with self.scope(DshModelAuditWriteRepository) as repository:
                row = repository.one(DshModelCall, DshModelCall.request_id == event.request_id)
                values = {key: value for key, value in event.model_dump().items() if key in DshModelCall.model_fields}
                if row is None:
                    row = DshModelCall(**values)
                else:
                    for key, value in values.items():
                        setattr(row, key, value)
                repository.session.add(row)

        await asyncio.to_thread(write)

    def bind_tools(self, _tools, **_kwargs):
        return self

    async def ainvoke(self, _messages, **_kwargs):
        self.calls += 1
        if self.model_failure:
            raise ConnectionError("Synthetic model failure")
        return AIMessage(
            content="fixture-reply",
            usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
            response_metadata={"finish_reason": "stop"},
        )

    async def astream(self, _messages, **_kwargs):
        self.calls += 1
        if self.model_failure:
            raise ConnectionError("Synthetic model failure")
        yield AIMessageChunk(content="fixture-")
        await asyncio.sleep(0)
        yield AIMessageChunk(content="reply", response_metadata={"finish_reason": "stop"})
        yield AIMessageChunk(content="", usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12})

    def build_app(self):
        app = FastAPI()
        from fastapi.responses import JSONResponse

        from bisheng.common.errcode.base import BaseErrorCode

        @app.exception_handler(BaseErrorCode)
        async def business_error(_request, error):
            return JSONResponse(error.return_resp_instance().model_dump())

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://127.0.0.1:3301", "http://localhost:3301"],
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )
        app.include_router(models.router, prefix="/api/v1")
        app.include_router(model_audit_admin.router, prefix="/api/v1")

        async def desktop(request: Request):
            token = request.headers.get("authorization", "").removeprefix("Bearer ")
            user = self.tokens.get(token)
            if user not in {20, 21, 30}:
                raise HTTPException(401, "Synthetic credential required")
            return DshPrincipal(
                tenant_id="3" if user == 30 else "2",
                user_id=str(user),
                seat_id="synthetic-seat",
                session_id="synthetic-session",
                grant_version=1,
            )

        async def admin(request: Request):
            actor = self.tokens.get(request.headers.get("authorization", "").removeprefix("Bearer "))
            if actor not in {1, 2}:
                raise HTTPException(403, "Synthetic administrator required")
            return SimpleNamespace(user_id=actor)

        class Runtime:
            settings = SimpleNamespace(billing_timezone="Asia/Shanghai")
            model = self.service

            async def complete(_self, principal, request, **kwargs):
                return await self.service.complete(principal, request, **kwargs)

            async def prepare_month(_self, principal, month):
                return {
                    "used": 0,
                    "limit": 100000,
                    "remaining": 100000,
                    "source": "live",
                    "quota_state": "ready",
                    "as_of": datetime.now(UTC),
                }

        runtime = SimpleNamespace(models=Runtime(), settings=Runtime.settings)
        app.dependency_overrides[get_runtime] = lambda: runtime
        app.dependency_overrides[models.desktop_principal] = desktop
        app.dependency_overrides[model_audit_admin.audit_admin] = admin
        app.dependency_overrides[model_audit_admin.get_audit_management] = lambda: self.admin

        @app.get("/api/v1/dsh/config")
        async def config():
            return {
                "enabled": True,
                "client_id": "dsh-desktop",
                "contract_version": "0.5.0",
                "audit_context": {"fields": list(AUDIT_FIELDS)},
            }

        @app.get("/health")
        async def health():
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return {
                "fixture": True,
                "calls": self.calls,
                "written": self.writer.written,
                "failed": self.writer.failed,
                "peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
            }

        @app.get("/fixture/usage/{request_id}")
        async def persisted_usage(request_id: str, request: Request):
            await admin(request)

            def read():
                with self.scope(DshModelAuditWriteRepository) as repository:
                    row = repository.one(DshModelCall, DshModelCall.request_id == request_id)
                    return {
                        "source": "dsh_model_call",
                        "status": row.status if row else None,
                        "total_tokens": row.total_tokens if row else None,
                    }

            return await run_audit_blocking(read)

        return app

    async def drain(self):
        for _ in range(400):
            if (
                not self.queue.used_bytes
                and not self.queue.bodies.used_bytes
                and not self.evidence.used_bytes
                and not self.annotations.used_bytes
            ):
                return
            await asyncio.sleep(0.01)
        raise TimeoutError("Controlled audit drain timed out")

    async def close(self):
        if self.activity:
            await self.activity.close()
        await asyncio.gather(self.queue.close(5), self.evidence.close(5), self.annotations.close(5))
