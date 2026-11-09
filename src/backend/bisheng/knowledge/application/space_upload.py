"""One invocation's initial SPACE uploads; SQL sessions never span external IO.

This owns only receipts issued during this invocation. The original container
authorization and request identity remain caller-owned; dispatch stays outside.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from weakref import WeakSet

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import (
    get_admin_scope_tenant_id,
    get_current_tenant_id,
    get_is_management_api,
    is_management_all_tenants,
    is_tenant_filter_bypassed,
)
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.knowledge.application.web_link_upload import PreparedWebLink, WebLinkObject, build_web_link_objects
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import FileSource, KnowledgeFile
from bisheng.knowledge.domain.repositories.folder_upload_registration_repository import (
    FolderUploadRegistrationRepository,
    NewUploadFolder,
)
from bisheng.knowledge.domain.repositories.upload_registration_repository import (
    NewUploadFile,
    UploadRegistrationRepository,
)
from bisheng.knowledge.domain.services.knowledge_processing_guard import require_space_processing_idle
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService, PreparedUpload
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils
from bisheng.permission.application.access import get_f048_resource_adapter
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL
from bisheng.permission.application.identity import PermissionActor, resolve_permission_actor
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason="space_upload_" + reason)


def _identity_error():
    raise ResourceReferenceInvalidError(reason="space_upload_identity_changed_or_unbound")


@dataclass(slots=True, repr=False)
class _Creation:
    registration: object
    tenant_id: int
    parent_type: str
    parent_id: int
    file_id: int
    document_id: int | None
    version_id: int | None
    object_name: str | None = None
    bucket_name: str | None = None
    stage: str = "registered"
    commit_outcome: str = "not_attempted"
    acknowledged: bool = False
    rolled_back: bool = False
    blob_attempted: bool = False
    objects: tuple[WebLinkObject, ...] = ()
    attempted_objects: tuple[str, ...] = ()
    storage: object = None
    record: object = None
    delete_outcome: str = "not_attempted"
    cleaned: bool = False


class SpaceUploadApplication:
    def __init__(
        self,
        *,
        login_user,
        session_factory,
        admit_upload,
        make_permission_record,
        actor_provider,
        repository=None,
        folder_repository=None,
    ):
        if not isinstance(login_user, UserPayload) or not all(
            callable(value) for value in (session_factory, admit_upload, make_permission_record, actor_provider)
        ):
            _blocked("original_identity_and_ports_required")
        if repository is not None and not isinstance(repository, UploadRegistrationRepository):
            _blocked("actual_registration_repository_required")
        if folder_repository is not None and not isinstance(folder_repository, FolderUploadRegistrationRepository):
            _blocked("actual_folder_repository_required")
        self.user, self.sessions = login_user, session_factory
        self.admit, self.make_record, self.actor_provider = admit_upload, make_permission_record, actor_provider
        self.repository = repository if repository is not None else UploadRegistrationRepository()
        self.folder_repository = (
            folder_repository if folder_repository is not None else FolderUploadRegistrationRepository()
        )
        self.identity = AuthenticatedSourceReadIdentity()
        self._original_identity, self._stopped = None, False
        self._creations, self._seen = [], WeakSet()
        self._folders = []

    async def _check_identity(self, tenant):
        if (
            type(tenant) is not int
            or tenant <= 0
            or get_current_tenant_id() != tenant
            or type(get_current_tenant_id()) is not int
            or is_tenant_filter_bypassed()
            or is_management_all_tenants()
        ):
            _identity_error()
        management = (get_is_management_api(), get_admin_scope_tenant_id())
        actor = await self.actor_provider()
        if not isinstance(actor, PermissionActor) or actor != await resolve_permission_actor(self.user):
            _identity_error()
        super_scope = (
            actor.subject_type == "user"
            and actor.subject_id == self.user.user_id
            and actor.super_admin
            and self.user.is_global_super
            and actor.data_scope == DATA_SCOPE_ALL
            and actor.current_tenant_id == self.user.tenant_id
        )
        if (
            actor.current_tenant_id != self.user.tenant_id
            or (actor.subject_type == "user" and actor.subject_id != self.user.user_id)
            or (actor.current_tenant_id != tenant and not (super_scope and management == (True, tenant)))
            or (management[1] is not None and not (super_scope and management == (True, tenant)))
        ):
            _identity_error()
        facts = await self.identity.acapture(self.user)
        current = (facts, management, actor)
        if facts.request_tenant_id != tenant or management != (get_is_management_api(), get_admin_scope_tenant_id()):
            _identity_error()
        if self._original_identity is None:
            self._original_identity = current
        elif self._original_identity != current:
            _identity_error()
        return actor

    @asynccontextmanager
    async def _session(self):
        original_error = None
        try:
            async with self.sessions() as session:
                try:
                    if not isinstance(session, AsyncSession) or session.in_transaction() or session in self._seen:
                        _blocked("fresh_owned_session_required")
                    self._seen.add(session)
                    yield session
                except BaseException as error:
                    original_error = error
                    raise
        except BaseException as error:
            if original_error is not None and error is not original_error:
                logger.opt(exception=True).error("Owned upload session close failed after a primary error")
                raise original_error
            raise
        if original_error is not None:
            # A factory cannot suppress a failed/unknown COMMIT into success.
            raise original_error

    def _progress(self):
        return tuple(
            {
                name: getattr(item, name)
                for name in (
                    "tenant_id",
                    "file_id",
                    "document_id",
                    "version_id",
                    "stage",
                    "commit_outcome",
                    "acknowledged",
                    "blob_attempted",
                    "delete_outcome",
                    "cleaned",
                )
            }
            for item in (*self._creations, *self._folders)
        )

    def _report(self, error):
        progress = self._progress()
        error.space_upload_progress = progress
        if isinstance(error, BaseErrorCode):
            error.kwargs["space_upload_progress"] = progress

    @staticmethod
    async def _rollback_owned(session):
        try:
            if session.in_transaction():
                await session.rollback()
        except BaseException:
            # Secondary cleanup, including cancellation, cannot replace the
            # original failure or establish that an unknown COMMIT did not run.
            logger.opt(exception=True).error("Owned initial upload SQL rollback failed")
            return False
        return True

    async def _register(self, knowledge, parent_id, prepared, file_source):
        entry = None
        web = type(prepared) is PreparedWebLink
        async with self._session() as session:
            await session.begin()
            try:
                actual = await self.repository.alock_space_for_upload(session, space_id=knowledge.id)
                require_space_processing_idle(actual, operation="upload_file")
                (receipt,) = await self.repository.aregister_initial(
                    session,
                    space_id=actual.id,
                    parent_id=parent_id,
                    files=(
                        NewUploadFile(
                            file_name=prepared.file_name if web else prepared.original_file_name,
                            file_size=len(prepared.markdown_bytes) if web else prepared.file_size,
                            md5=prepared.content_hash if web else prepared.md5,
                            split_rule=prepared.split_rule,
                            file_source=FileSource.WEB_LINK.value if web else file_source.value,
                            user_metadata={},
                            user_id=self.user.user_id,
                            user_name=self.user.user_name,
                            updater_id=self.user.user_id,
                            updater_name=self.user.user_name,
                        ),
                    ),
                )
                entry = _Creation(
                    receipt,
                    actual.tenant_id,
                    "folder" if parent_id is not None else "knowledge_space",
                    parent_id if parent_id is not None else actual.id,
                    receipt.file.id,
                    receipt.document_id,
                    receipt.version_id,
                )
                self._creations.append(entry)
                if web:
                    plan = build_web_link_objects(prepared, file_id=receipt.file.id)
                    entry.objects, entry.object_name = plan.objects, plan.objects[0].name
                    entry.registration = await self.repository.aset_materialized(
                        session, registration=receipt, object_name=entry.object_name, user_metadata=plan.user_metadata
                    )
                else:
                    key = KnowledgeUtils.get_knowledge_file_object_name(receipt.file.id, receipt.file.file_name)
                    entry.object_name = key
                    entry.registration = await self.repository.areserve_object_key(
                        session, registration=receipt, object_name=key
                    )
                entry.stage, entry.commit_outcome = "commit", "unknown"
                await session.commit()
                entry.commit_outcome = "ack"
                self.repository._acknowledge_committed_initial(registrations=(entry.registration,))
                entry.acknowledged, entry.stage = True, "committed"
            except BaseException:
                rolled_back = await self._rollback_owned(session)
                if entry is not None and entry.commit_outcome == "not_attempted":
                    entry.rolled_back = rolled_back
                raise
        return entry

    def _record(self, entry, row, *, resource_type="knowledge_file"):
        if entry.record is None:
            entry.record = self.make_record(
                row=row, resource_type=resource_type, parent_type=entry.parent_type, parent_id=entry.parent_id
            )
        return entry.record

    async def _admit_destination(self, knowledge, parent_id, file_source=FileSource.SPACE_UPLOAD):
        if self._stopped:
            _blocked("invocation_stopped")
        if (
            not isinstance(knowledge, Knowledge)
            or type(knowledge.id) is not int
            or knowledge.id <= 0
            or knowledge.type != 3
        ):
            _blocked("actual_space_required")
        if parent_id is not None and (type(parent_id) is not int or parent_id <= 0):
            _blocked("invalid_parent")
        if not isinstance(file_source, FileSource):
            _blocked("actual_file_source_required")
        await self._check_identity(knowledge.tenant_id)
        await self.admit(
            "folder" if parent_id is not None else "knowledge_space", parent_id or knowledge.id, "upload_file"
        )
        await self._check_identity(knowledge.tenant_id)

    async def acreate_file(
        self, *, knowledge: Knowledge, parent_id: int | None, prepared: PreparedUpload, file_source: FileSource
    ) -> KnowledgeFile:
        try:
            await self._admit_destination(knowledge, parent_id, file_source)
            entry = await self._register(knowledge, parent_id, prepared, file_source)
            await self._check_identity(entry.tenant_id)
            entry.stage = "telemetry"
            KnowledgeService.audit_telemetry_service.telemetry_new_knowledge_file(self.user)
            await self._check_identity(entry.tenant_id)
            entry.stage = "blob"
            entry.storage = get_minio_storage_sync()
            entry.bucket_name = entry.storage.bucket
            await self._check_identity(entry.tenant_id)
            entry.blob_attempted = True
            entry.storage.put_object_sync(
                bucket_name=entry.bucket_name,
                object_name=entry.object_name,
                file=prepared.local_path,
            )
            await self._check_identity(entry.tenant_id)
            entry.stage = "temporary_cleanup"
            KnowledgeService.remove_unused_file(prepared.file_info.file_path)
            await self._check_identity(entry.tenant_id)
            entry.stage = "projection"
            adapter = await get_f048_resource_adapter("knowledge_file")
            actor = await self._check_identity(entry.tenant_id)
            await adapter.authorize_created(record=self._record(entry, entry.registration.file), actor=actor)
            await self._check_identity(entry.tenant_id)
            entry.stage = "created"
            return entry.registration.file
        except BaseException as error:
            self._stopped = True
            self._report(error)
            raise

    async def acreate_web_link(
        self, *, knowledge: Knowledge, parent_id: int | None, prepared: PreparedWebLink
    ) -> KnowledgeFile:
        try:
            await self._admit_destination(knowledge, parent_id, FileSource.WEB_LINK)
            if type(prepared) is not PreparedWebLink:
                _blocked("actual_web_material_required")
            entry = await self._register(knowledge, parent_id, prepared, FileSource.WEB_LINK)
            await self._check_identity(entry.tenant_id)
            entry.stage = "blob"
            entry.storage = get_minio_storage_sync()
            entry.bucket_name = entry.storage.bucket
            for item in entry.objects:
                await self._check_identity(entry.tenant_id)
                # Even a failed PUT may have persisted its object remotely.
                entry.attempted_objects += (item.name,)
                entry.blob_attempted = True
                entry.storage.put_object_sync(
                    bucket_name=entry.bucket_name,
                    object_name=item.name,
                    file=item.content,
                    content_type=item.content_type,
                )
                await self._check_identity(entry.tenant_id)
            entry.stage = "projection"
            adapter = await get_f048_resource_adapter("knowledge_file")
            actor = await self._check_identity(entry.tenant_id)
            await adapter.authorize_created(record=self._record(entry, entry.registration.file), actor=actor)
            await self._check_identity(entry.tenant_id)
            entry.stage = "created"
            return entry.registration.file
        except BaseException as error:
            self._stopped = True
            self._report(error)
            raise

    async def _precheck(self, entry):
        async with self._session() as session, session.begin():
            await self.repository._arebind_committed_initial(session, registration=entry.registration)

    async def _register_folder(self, knowledge, parent_id, folder_name):
        entry = None
        async with self._session() as session:
            await session.begin()
            try:
                actual = await self.repository.alock_space_for_upload(session, space_id=knowledge.id)
                require_space_processing_idle(actual, operation="upload_folder_items")
                registration = await self.folder_repository.aregister_folder(
                    session,
                    space_id=actual.id,
                    parent_id=parent_id,
                    folder=NewUploadFolder(
                        folder_name, self.user.user_id, self.user.user_name, self.user.user_id, self.user.user_name
                    ),
                )
                entry = _Creation(
                    registration,
                    actual.tenant_id,
                    "folder" if parent_id is not None else "knowledge_space",
                    parent_id if parent_id is not None else actual.id,
                    registration.file.id,
                    None,
                    None,
                )
                self._folders.append(entry)
                entry.stage, entry.commit_outcome = "commit", "unknown"
                await session.commit()
                entry.commit_outcome = "ack"
                entry.registration = self.folder_repository._acknowledge_committed_folder(registration=registration)
                entry.acknowledged, entry.stage = True, "committed"
            except BaseException:
                rolled_back = await self._rollback_owned(session)
                if entry is not None and entry.commit_outcome == "not_attempted":
                    entry.rolled_back = rolled_back
                raise
        return entry

    async def acreate_folder(self, *, knowledge: Knowledge, parent_id: int | None, folder_name: str) -> KnowledgeFile:
        try:
            await self._admit_destination(knowledge, parent_id)
            entry = await self._register_folder(knowledge, parent_id, folder_name)
            await self._check_identity(entry.tenant_id)
            entry.stage = "projection"
            adapter = await get_f048_resource_adapter("folder")
            actor = await self._check_identity(entry.tenant_id)
            await adapter.authorize_created(
                record=self._record(entry, entry.registration.file, resource_type="folder"), actor=actor
            )
            await self._check_identity(entry.tenant_id)
            entry.stage = "created"
            return entry.registration.file
        except BaseException as error:
            self._stopped = True
            self._report(error)
            raise

    async def _folder_delete_sql(self, entry):
        async with self._session() as session:
            await session.begin()
            try:
                local = await self.folder_repository._arebind_owned_empty_folder(
                    session, registration=entry.registration
                )
                await self.folder_repository.arollback_created_empty(session, receipt=local)
                entry.delete_outcome = "unknown"
                await session.commit()
                entry.delete_outcome = "ack"
            except BaseException:
                await self._rollback_owned(session)
                raise

    async def _rollback_folders(self):
        errors = []
        for entry in reversed(self._folders):
            if entry.cleaned or entry.rolled_back:
                continue
            try:
                if entry.delete_outcome != "not_attempted":
                    _blocked("cleanup_result_requires_reconciliation")
                await self._check_identity(entry.tenant_id)
                entry.stage = "rollback_precheck"
                async with self._session() as session, session.begin():
                    await self.folder_repository._arebind_owned_empty_folder(session, registration=entry.registration)
                await self._check_identity(entry.tenant_id)
                entry.stage = "rollback_projection"
                adapter = await get_f048_resource_adapter("folder")
                actor = await self._check_identity(entry.tenant_id)
                await adapter.rollback_created(
                    record=self._record(entry, entry.registration.file, resource_type="folder"), actor=actor
                )
                await self._check_identity(entry.tenant_id)
                entry.stage = "rollback_sql"
                await self._folder_delete_sql(entry)
                await self._check_identity(entry.tenant_id)
                entry.cleaned, entry.stage = True, "cleaned"
            except Exception as error:
                self._report(error)
                errors.append(error)
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise ExceptionGroup("Folder upload compensation failed", errors)

    async def _delete_sql(self, entry):
        async with self._session() as session:
            await session.begin()
            try:
                local = await self.repository._arebind_committed_initial(session, registration=entry.registration)
                await self.repository.arollback_created(session, registrations=(local,))
                entry.delete_outcome = "unknown"
                await session.commit()
                entry.delete_outcome = "ack"
            except BaseException:
                await self._rollback_owned(session)
                raise

    async def arollback_created(self) -> None:
        self._stopped = True
        try:
            # An unknown original COMMIT supplies neither an ACK receipt nor
            # permission to infer absence and perform destructive compensation.
            if any(
                not row.cleaned and not row.rolled_back and not row.acknowledged
                for row in (*self._creations, *self._folders)
            ):
                _blocked("unacknowledged_creation")
            errors = []
            for entry in reversed(self._creations):
                if entry.cleaned or entry.rolled_back:
                    continue
                try:
                    if entry.delete_outcome != "not_attempted":
                        _blocked("cleanup_result_requires_reconciliation")
                    await self._check_identity(entry.tenant_id)
                    entry.stage = "rollback_precheck"
                    await self._precheck(entry)
                    await self._check_identity(entry.tenant_id)
                    entry.stage = "rollback_projection"
                    adapter = await get_f048_resource_adapter("knowledge_file")
                    actor = await self._check_identity(entry.tenant_id)
                    await adapter.rollback_created(record=self._record(entry, entry.registration.file), actor=actor)
                    await self._check_identity(entry.tenant_id)
                    entry.stage = "rollback_sql"
                    await self._delete_sql(entry)
                    await self._check_identity(entry.tenant_id)
                    entry.stage = "rollback_blob"
                    if entry.blob_attempted:
                        for key in reversed(entry.attempted_objects or (entry.object_name,)):
                            entry.storage.remove_object_sync(bucket_name=entry.bucket_name, object_name=key)
                    entry.cleaned, entry.stage = True, "cleaned"
                except Exception as error:
                    self._report(error)
                    errors.append(error)
            if len(errors) == 1:
                raise errors[0]
            if errors:
                raise ExceptionGroup("Initial upload compensation failed", errors)
            # Files must be confirmed gone before any owned parent folder.
            await self._rollback_folders()
        except BaseException as error:
            self._report(error)
            raise


def make_space_upload_application(service):
    """Composition port for existing real-user channel HTTP and worker writers."""
    from bisheng.core.database import get_async_db_session

    return SpaceUploadApplication(
        login_user=service.login_user,
        session_factory=get_async_db_session,
        admit_upload=service._require_action,
        make_permission_record=service._new_file_permission_record,
        actor_provider=service._permission_actor,
    )
