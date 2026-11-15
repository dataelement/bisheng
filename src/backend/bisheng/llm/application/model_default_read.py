"""Tenant-default repair reads and whole-source execution admission."""

import json
from dataclasses import dataclass

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.llm.application.model_default_read_identity import ModelDefaultReadIdentityPort
from bisheng.llm.domain.repositories.model_default_repository import ModelDefaultRepository
from bisheng.llm.domain.services.default_reference_extractor import extract_model_default_references
from bisheng.resource_reference.application.contracts import SourceKey
from bisheng.resource_reference.application.source_contracts import SourceReadRequest
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime


@dataclass(frozen=True, slots=True)
class AdmittedModelDefault:
    key: str
    payload_json: str
    source_key: SourceKey | None


class ModelDefaultReadRuntime:
    def __init__(self, core_runtime, identity_port, repository=None):
        if not isinstance(core_runtime, ReferenceSourceReadRuntime) or not isinstance(
            identity_port, ModelDefaultReadIdentityPort
        ):
            raise TypeError("default reads require an explicitly assembled core and ambient identity port")
        self.core = core_runtime
        self.identity_port = identity_port
        self.repository = repository if repository is not None else ModelDefaultRepository()

    def get_default(self, key, login_user=None, session=None):
        identity = self.identity_port.issue_identity(login_user)
        if session is None:
            with get_sync_db_session() as active:
                return self.get_default(key, login_user=login_user, session=active)
        result = self.repository.resolve(session, key)
        self.identity_port.capture(identity)
        return result

    async def aget_default(self, key, login_user=None, session=None):
        identity = self.identity_port.issue_identity(login_user)
        if session is None:
            async with get_async_db_session() as active:
                return await self.aget_default(key, login_user=login_user, session=active)
        result = await self.repository.aresolve(session, key)
        await self.identity_port.acapture(identity)
        return result

    def require_default(self, key, login_user=None, session=None):
        identity = self.identity_port.issue_identity(login_user)
        if session is None:
            with get_sync_db_session() as active:
                return self.require_default(key, login_user=login_user, session=active)
        candidate = self.repository.resolve(session, key)
        self.identity_port.capture(identity)
        if candidate.source is None:
            return AdmittedModelDefault(key, "{}", None)
        scope = self.core.verifier.issue_scope(session, SourceReadRequest("model_default", key), identity)
        current = self.core.require_source_valid(session, scope, identity).snapshot
        return AdmittedModelDefault(key, current.payload_json, current.source_key)

    async def arequire_default(self, key, login_user=None, session=None):
        identity = self.identity_port.issue_identity(login_user)
        if session is None:
            async with get_async_db_session() as active:
                return await self.arequire_default(key, login_user=login_user, session=active)
        candidate = await self.repository.aresolve(session, key)
        await self.identity_port.acapture(identity)
        if candidate.source is None:
            return AdmittedModelDefault(key, "{}", None)
        scope = await self.core.verifier.aissue_scope(session, SourceReadRequest("model_default", key), identity)
        current = (await self.core.arequire_source_valid(session, scope, identity)).snapshot
        return AdmittedModelDefault(key, current.payload_json, current.source_key)

    @staticmethod
    def _slot(configuration, slot_key):
        references = extract_model_default_references(configuration.key, json.loads(configuration.payload_json))
        return next((item.target.target_id for item in references if item.slot_key == slot_key), None)

    def require_default_slot(self, key, slot_key, login_user=None, session=None):
        return self._slot(self.require_default(key, login_user=login_user, session=session), slot_key)

    async def arequire_default_slot(self, key, slot_key, login_user=None, session=None):
        return self._slot(await self.arequire_default(key, login_user=login_user, session=session), slot_key)


_runtime: ModelDefaultReadRuntime | None = None


def configure_model_default_read_runtime(runtime: ModelDefaultReadRuntime | None) -> None:
    global _runtime
    if runtime is not None and not isinstance(runtime, ModelDefaultReadRuntime):
        raise TypeError("a fully assembled model-default read runtime is required")
    _runtime = runtime


def get_model_default_read_runtime() -> ModelDefaultReadRuntime:
    if _runtime is None:
        raise ReferenceCoverageNotReadyError(reason="model_default_read_runtime_unconfigured")
    return _runtime
