"""One short transaction for the original link, merge and primary use cases.

The existing login/feature/business qualification is preserved. This adds no
permission action and performs no object, provider, queue or audit I/O.
"""

from contextlib import asynccontextmanager
from weakref import WeakSet

from fastapi import HTTPException
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.errcode.knowledge_space import (
    VersionLinkFileNotReadyError,
    VersionLinkSourceFileMissingError,
    VersionLinkSourceMultiVersionError,
    VersionLinkTargetUnavailableError,
)
from bisheng.core.context.tenant import (
    get_admin_scope_tenant_id,
    get_current_tenant_id,
    get_is_management_api,
    get_visible_tenant_ids,
    is_tenant_filter_bypassed,
)
from bisheng.knowledge.domain.repositories.knowledge_version_mutation_repository import (
    KnowledgeVersionMutationRepository,
)
from bisheng.knowledge.domain.services.knowledge_processing_guard import require_space_processing_idle
from bisheng.open_api.domain.context import get_current_open_api_principal
from bisheng.permission.application.identity import get_current_permission_actor


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason=f"version_mutation_application_{reason}")


def _identity(user):
    tenant = get_current_tenant_id()
    if not isinstance(user, UserPayload) or type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed():
        _blocked("original_identity_scope_required")
    # Observe the original objects/context, never replace or derive an actor.
    # A trusted selected management tenant need not equal the user's JWT home.
    return (
        user.user_id,
        user.tenant_id,
        tenant,
        get_visible_tenant_ids(),
        get_is_management_api(),
        get_admin_scope_tenant_id(),
        get_current_permission_actor(),
        get_current_open_api_principal(),
    )


def _source(file):
    if file is None:
        raise VersionLinkSourceFileMissingError()
    if file.status != 2:
        raise VersionLinkFileNotReadyError()


class KnowledgeVersionMutationApplication:
    def __init__(self, *, session_factory, require_version_management_enabled, repository=None):
        if not callable(session_factory) or not callable(require_version_management_enabled):
            _blocked("native_ports_required")
        if repository is not None and not isinstance(repository, KnowledgeVersionMutationRepository):
            _blocked("actual_repository_required")
        self.sessions, self.enabled = session_factory, require_version_management_enabled
        self.repository = repository if repository is not None else KnowledgeVersionMutationRepository()
        self._seen = WeakSet()

    @staticmethod
    def _current(user, identity):
        if _identity(user) != identity:
            _blocked("identity_scope_changed")

    @asynccontextmanager
    async def _transaction(self):
        original = None
        try:
            async with self.sessions() as session:
                try:
                    if not isinstance(session, AsyncSession) or session.in_transaction() or session in self._seen:
                        _blocked("fresh_native_session_required")
                    self._seen.add(session)
                    async with session.begin():
                        try:
                            yield session
                        except BaseException as error:
                            original = error
                            raise
                except BaseException as error:
                    # Capture commit errors too, before the owning factory's
                    # rollback/close can replace an uncertain commit outcome.
                    original = original if original is not None else error
                    raise
        except BaseException as error:
            if original is not None and error is not original:
                logger.opt(exception=True).error("Version mutation cleanup failed after an original error")
                raise original
            raise
        if original is not None:
            # A suppressing factory cannot turn body/commit failure into success.
            raise original

    async def _execute(self, user, operation, inputs):
        identity = _identity(user)
        await self.enabled()  # The original feature/config I/O precedes SQL locks.
        self._current(user, identity)
        async with self._transaction() as session:
            self._current(user, identity)
            if operation == "link":
                state = await self.repository.alock_link_state(session, **inputs)
                self._link(state)
            elif operation == "merge":
                state = await self.repository.alock_merge_state(session, **inputs)
                self._merge(state)
            else:
                state = await self.repository.alock_primary_state(session, **inputs)
                self._primary(state)
            self._current(user, identity)
            require_space_processing_idle(
                state.space,
                operation={"link": "link_version", "merge": "merge_versions", "primary": "set_primary_version"}[
                    operation
                ],
            )
            if operation == "primary":
                result = await self.repository.aset_primary(session, state=state)
            else:
                next_no = max(row.version_no for row in state.target_versions) + 1
                result = await self.repository.arelink(session, state=state, new_version_no=next_no)
            self._current(user, identity)
        # Returning is after the one awaited root commit ACK. Unknown commit
        # errors propagate unchanged; never retry or infer a compensating write.
        self._current(user, identity)
        return result

    @staticmethod
    def _duplicate(state, message):
        by_id = {row.id: row for row in state.files}
        incoming = state.incoming_file
        if incoming.md5 and any(
            file is not None and file.md5 and file.md5 == incoming.md5
            for row in state.target_versions
            for file in (by_id.get(row.knowledge_file_id),)
        ):
            raise HTTPException(status_code=409, detail=message)

    @classmethod
    def _link(cls, state):
        _source(state.incoming_file)
        if len(state.source_versions) >= 2:
            raise VersionLinkSourceMultiVersionError()
        target = state.target_document
        primary = next((row for row in state.target_versions if target and row.id == target.primary_version_id), None)
        file = next((row for row in state.files if primary and row.id == primary.knowledge_file_id), None)
        if target is None or primary is None or file is None or file.status != 2:
            raise VersionLinkTargetUnavailableError()
        if target.knowledge_id != state.incoming_file.knowledge_id:
            raise HTTPException(status_code=409, detail="target document belongs to a different space")
        cls._duplicate(state, "duplicate content already in target chain")

    @classmethod
    def _merge(cls, state):
        _source(state.anchor_file)
        if state.target_document is None:
            raise VersionLinkFileNotReadyError()
        if state.source_document is None:
            raise VersionLinkSourceFileMissingError()
        if state.source_document.knowledge_id != state.anchor_file.knowledge_id:
            raise HTTPException(status_code=409, detail="source document belongs to a different space")
        if len(state.source_versions) >= 2:
            raise VersionLinkSourceMultiVersionError()
        if not state.source_versions:
            raise VersionLinkSourceFileMissingError()
        _source(state.incoming_file)
        cls._duplicate(state, "duplicate content already in current chain")

    @staticmethod
    def _primary(state):
        if state.selected_version_id is None:
            raise HTTPException(status_code=404, detail="version not found")
        if state.incoming_file is None or state.incoming_file.status != 2:
            raise HTTPException(status_code=412, detail="target version not parsed successfully")

    async def alink_file(self, *, login_user, knowledge_file_id, target_document_id):
        return await self._execute(
            login_user, "link", {"knowledge_file_id": knowledge_file_id, "target_document_id": target_document_id}
        )

    async def amerge_document(self, *, login_user, current_knowledge_file_id, source_document_id):
        return await self._execute(
            login_user,
            "merge",
            {"current_file_id": current_knowledge_file_id, "source_document_id": source_document_id},
        )

    async def aset_primary(self, *, login_user, version_id):
        return await self._execute(login_user, "primary", {"version_id": version_id})
