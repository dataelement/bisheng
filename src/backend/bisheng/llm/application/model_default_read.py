"""Tenant-default repair reads, strict whole-source and selected-slot admission."""

import json
from dataclasses import dataclass

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.llm.application.model_default_read_identity import ModelDefaultReadIdentityPort
from bisheng.llm.domain.repositories.model_default_repository import ModelDefaultRepository
from bisheng.llm.domain.services.default_reference_extractor import (
    extract_model_default_references,
    model_default_models_are_callable,
    project_model_default,
    validate_model_default_slots,
)
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
        self._validate_model_states(
            key,
            current.references,
            self.repository.read_slot_models(
                session, tuple(int(reference.target.target_id) for reference in current.references)
            ),
        )
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
        self._validate_model_states(
            key,
            current.references,
            await self.repository.aread_slot_models(
                session, tuple(int(reference.target.target_id) for reference in current.references)
            ),
        )
        return AdmittedModelDefault(key, current.payload_json, current.source_key)

    @staticmethod
    def _references(key, payload_json):
        try:
            return extract_model_default_references(key, json.loads(payload_json))
        except (TypeError, ValueError) as error:
            raise ResourceReferenceInvalidError(reason="model_default_configuration_invalid") from error

    @staticmethod
    def _validate_model_states(key, references, states):
        if not model_default_models_are_callable(key, references, states):
            raise ResourceReferenceInvalidError(reason="reference_target_invalid")

    @staticmethod
    def _project(snapshot, key, slots):
        payload = project_model_default(key, json.loads(snapshot.payload_json), slots)
        return AdmittedModelDefault(key, json.dumps(payload), snapshot.source_key)

    def require_default_projection(self, key, slots, login_user=None, session=None):
        identity = self.identity_port.issue_identity(login_user)
        if session is None:
            with get_sync_db_session() as active:
                return self.require_default_projection(key, slots, login_user=login_user, session=active)
        candidate = self.repository.resolve(session, key)
        self.identity_port.capture(identity)
        references = self._references(key, candidate.payload_json)
        try:
            validate_model_default_slots(key, slots, references)
        except ValueError as error:
            raise ResourceReferenceInvalidError(reason="model_default_slot_invalid") from error
        if candidate.source is None:
            return AdmittedModelDefault(key, json.dumps(project_model_default(key, {}, slots)), None)
        scope = self.core.verifier.issue_scope(session, SourceReadRequest("model_default", key), identity)
        current = self.core.require_default_slots_valid(
            session,
            scope,
            identity,
            tuple(slot for slot in slots if any(ref.slot_key == slot for ref in scope.snapshot.references)),
        ).snapshot
        selected = tuple(reference for reference in current.references if reference.slot_key in slots)
        states = self.repository.read_slot_models(
            session, tuple(int(reference.target.target_id) for reference in selected)
        )
        self._validate_model_states(key, selected, states)
        return self._project(current, key, slots)

    async def arequire_default_projection(self, key, slots, login_user=None, session=None):
        identity = self.identity_port.issue_identity(login_user)
        if session is None:
            async with get_async_db_session() as active:
                return await self.arequire_default_projection(key, slots, login_user=login_user, session=active)
        candidate = await self.repository.aresolve(session, key)
        await self.identity_port.acapture(identity)
        references = self._references(key, candidate.payload_json)
        try:
            validate_model_default_slots(key, slots, references)
        except ValueError as error:
            raise ResourceReferenceInvalidError(reason="model_default_slot_invalid") from error
        if candidate.source is None:
            return AdmittedModelDefault(key, json.dumps(project_model_default(key, {}, slots)), None)
        scope = await self.core.verifier.aissue_scope(session, SourceReadRequest("model_default", key), identity)
        current = (
            await self.core.arequire_default_slots_valid(
                session,
                scope,
                identity,
                tuple(slot for slot in slots if any(ref.slot_key == slot for ref in scope.snapshot.references)),
            )
        ).snapshot
        selected = tuple(reference for reference in current.references if reference.slot_key in slots)
        states = await self.repository.aread_slot_models(
            session, tuple(int(reference.target.target_id) for reference in selected)
        )
        self._validate_model_states(key, selected, states)
        return self._project(current, key, slots)

    @staticmethod
    def _slot(configuration, slot_key):
        references = extract_model_default_references(configuration.key, json.loads(configuration.payload_json))
        return next((item.target.target_id for item in references if item.slot_key == slot_key), None)

    def require_default_slot(self, key, slot_key, login_user=None, session=None):
        return self._slot(
            self.require_default_projection(key, (slot_key,), login_user=login_user, session=session), slot_key
        )

    async def arequire_default_slot(self, key, slot_key, login_user=None, session=None):
        return self._slot(
            await self.arequire_default_projection(key, (slot_key,), login_user=login_user, session=session), slot_key
        )


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
