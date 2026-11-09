"""Request and native phase guards for the model Owner's deletion use case."""

from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError
from bisheng.common.errcode.llm import ModelNameRepeatError
from bisheng.llm.application.model_delete_plan import _identity_facts, _Scope, capture_model_identity
from bisheng.llm.domain.repositories.model_delete_plan_repository import _hash
from bisheng.llm.domain.repositories.model_provider_operation_repository import ModelProviderOperationRepository
from bisheng.llm.domain.schemas import LLMModelCreateReq, LLMServerCreateReq
from bisheng.permission.application.identity import (
    get_current_permission_actor,
    reset_current_permission_actor,
    resolve_permission_actor,
    set_current_permission_actor,
)
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository


def changed():
    raise KnowledgeOperationPlanChangedError()


@dataclass(frozen=True, slots=True)
class ModelDeleteCommand:
    operation: str
    server_id: int
    retained: tuple[int, ...]
    command_digest: str
    server: LLMServerCreateReq | None
    force: bool
    confirmation_id: str | None
    plan_digest: str | None

    @classmethod
    def create(cls, *, server=None, server_id=None, force=False, confirmation_id=None, plan_digest=None):
        if type(force) is not bool or (confirmation_id is None) != (plan_digest is None):
            changed()
        if force and confirmation_id is None:
            changed()
        if confirmation_id is not None and (
            not isinstance(confirmation_id, str)
            or not confirmation_id
            or not isinstance(plan_digest, str)
            or len(plan_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in plan_digest)
        ):
            changed()
        if server is None:
            operation, retained = "model_delete_server", ()
            payload = {"operation": operation, "server_id": server_id}
        else:
            if type(server) is not LLMServerCreateReq:
                changed()
            server = server.model_copy(deep=True)
            server_id, operation = server.id, "model_update_server"
            if type(server.models) is not list or any(type(value) is not LLMModelCreateReq for value in server.models):
                changed()
            if server.limit is None or server.limit_flag is None:
                changed()
            names = [value.model_name for value in server.models]
            if len(names) != len(set(names)):
                raise ModelNameRepeatError.http_exception()
            retained = tuple(
                value.id
                for value in server.models
                if value.id is not None and not (type(value.id) is int and value.id == 0)
            )
            if any(type(value) is not int or value <= 0 for value in retained) or len(set(retained)) != len(retained):
                changed()
            payload = {"operation": operation, "server": server.model_dump(mode="json")}
        if type(server_id) is not int or server_id <= 0:
            changed()
        return cls(operation, server_id, retained, _hash(payload), server, force, confirmation_id, plan_digest)


class ModelDeletionRequest:
    def __init__(self, identity, tenant_id, original):
        self.identity, self.tenant_id = identity, tenant_id
        self.facts, self.actor, self.actor_reference = original

    def check(self):
        if ReferenceRepository.current_tenant_id() != self.tenant_id or _identity_facts(self.identity) != self.facts:
            changed()

    async def call(self, method, *args, **kwargs):
        self.check()
        value = await method(*args, **kwargs)
        self.check()
        return value


@asynccontextmanager
async def model_deletion_request(identity, *, references, plans):
    before = _identity_facts(identity)
    actor = await resolve_permission_actor(identity)
    if _identity_facts(identity) != before:
        changed()
    # Resolve the original identity once outside target SQL. Keep an already
    # established actor verbatim; otherwise publish that exact resolved actor
    # only for this use case and restore the caller context afterwards.
    token = set_current_permission_actor(actor) if get_current_permission_actor() is None else None
    try:
        facts, tenant = _identity_facts(identity), ReferenceRepository.current_tenant_id()

        async def call(method, *args, **kwargs):
            if _identity_facts(identity) != facts or ReferenceRepository.current_tenant_id() != tenant:
                changed()
            result = await method(*args, **kwargs)
            if _identity_facts(identity) != facts or ReferenceRepository.current_tenant_id() != tenant:
                changed()
            return result

        await call(references._authorize, identity)
        original = await capture_model_identity(identity, tenant_id=tenant, plans=plans, call=call)
        yield ModelDeletionRequest(identity, tenant, original)
    finally:
        if token is not None:
            reset_current_permission_actor(token)


class ModelWritePhase:
    def __init__(self, session, request):
        self.session, self.request, self.scope = session, request, _Scope(session)
        self.check()

    def check(self):
        self.request.check()
        self.scope.check()
        ModelProviderOperationRepository._native(self.session)

    async def call(self, method, *args, **kwargs):
        self.check()
        value = await self.scope.call(method, *args, **kwargs)
        self.check()
        return value


@asynccontextmanager
async def model_write_phase(session_factory, request):
    request.check()
    async with session_factory() as session:
        if session.in_transaction():
            changed()
        async with session.begin():
            outer = _Scope(session)
            async with session.begin_nested():
                phase = ModelWritePhase(session, request)
                yield phase
                phase.check()
            outer.check()
            request.check()
            if session.new or session.dirty or session.deleted:
                changed()
    request.check()


def execution_frame(purpose, *, parent_confirmation_id=None, force=False):
    return {
        "version": 1,
        "purpose": purpose,
        "parent_confirmation_id": parent_confirmation_id,
        "sharing": None,
        "reserved_target_revisions": {},
        "ack": None,
        "force": force,
    }


def copied_metadata(row):
    return deepcopy(row.model_execution_metadata)
