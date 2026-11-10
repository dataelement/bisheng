"""Only execute an existing approved legacy request; never issue a new approval."""

from dataclasses import replace

from bisheng.approval.domain.repositories.legacy_upload_execution_repository import LegacyUploadExecutionRepository
from bisheng.approval.domain.services.approval_service import ApprovalService
from bisheng.common.errcode.approval import ApprovalRequestPermissionDeniedError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, tenant_execution_scope
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.space_upload import SpaceUploadApplication
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.open_api.application.access_context import get_current_open_api_principal
from bisheng.permission.application.identity import resolve_permission_actor
from bisheng.public_endpoints.application.access_context import get_current_public_api_principal
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity
from bisheng.user.application.runtime_identity import read_current_person_facts, resolve_preview_person


def _deny():
    raise ApprovalRequestPermissionDeniedError()


class _ApprovedUpload(SpaceUploadApplication):
    def __init__(self, *, evidence, guard, **kwargs):
        super().__init__(**kwargs)
        self._approved_evidence, self._approved_guard = evidence, guard

    def _new_upload_file(self, prepared, file_source, web):
        record = super()._new_upload_file(prepared, file_source, web)
        row = self._approved_evidence.row
        return replace(record, user_id=row.applicant_user_id, user_name=row.applicant_user_name)

    async def _check_identity(self, tenant):
        await super()._check_identity(tenant)
        await self._approved_guard()
        return await super()._check_identity(tenant)


def _check_context(tenant):
    if (
        type(tenant) is not int
        or tenant <= 0
        or get_current_tenant_id() != tenant
        or is_tenant_filter_bypassed()
        or get_current_open_api_principal() is not None
        or get_current_public_api_principal() is not None
    ):
        _deny()


async def _require_executor(executor, tenant):
    actor = await resolve_permission_actor(executor)
    _check_context(tenant)
    if (
        executor.tenant_id != tenant
        or actor.subject_type != "user"
        or actor.subject_id != executor.user_id
        or actor.current_tenant_id != tenant
        or actor.super_admin != executor.is_global_super
    ):
        _deny()


async def _require_applicant(row, tenant):
    people = await read_current_person_facts((row.applicant_user_id,))
    _check_context(tenant)
    applicant = people.get(row.applicant_user_id)
    if applicant is None or applicant["state"] != "active" or applicant["tenant_id"] != tenant:
        _deny()


async def finalize_approved_upload(*, request_id, operator_user_id):
    tenant = get_current_tenant_id()
    _check_context(tenant)
    executor = await resolve_preview_person(operator_user_id)
    _check_context(tenant)
    await _require_executor(executor, tenant)
    repository = LegacyUploadExecutionRepository()
    async with get_async_db_session() as session:
        evidence = await repository.acapture(
            session,
            request_id=request_id,
            operator_id=operator_user_id,
            tenant_id=tenant,
        )
        _check_context(tenant)
        await repository.acheck(session, evidence)
    _check_context(tenant)
    await _require_applicant(evidence.row, tenant)
    service = KnowledgeSpaceService(request=None, login_user=executor)
    row = evidence.row
    await service._require_action(
        "folder" if row.parent_folder_id is not None else "knowledge_space",
        row.parent_folder_id if row.parent_folder_id is not None else row.space_id,
        "upload_file",
    )
    _check_context(tenant)
    await _require_executor(executor, tenant)
    # Admit against the real HTTP tenant and actor before using KSS's original
    # tenant-local SQL/dispatch scope. No actor or person is replaced.
    with tenant_execution_scope(tenant):
        await _finalize_in_tenant(executor, service, repository, evidence, tenant)


async def _finalize_in_tenant(executor, service, repository, evidence, tenant):
    def check_context():
        _check_context(tenant)

    operator_user_id = executor.user_id
    identity = AuthenticatedSourceReadIdentity()
    original_identity = await identity.acapture(executor)
    row = evidence.row
    # This value has no authority. Keep the original applicant quota lookup,
    # including its non-admin marker, completely outside every identity port.
    service._upload_accounting_user = ApprovalService._build_system_login_user(
        user_id=row.applicant_user_id,
        user_name=row.applicant_user_name,
        tenant_id=row.tenant_id,
    )

    async def guard():
        check_context()
        current_executor = await resolve_preview_person(operator_user_id)
        check_context()
        if await identity.acapture(current_executor) != original_identity:
            _deny()
        check_context()
        await _require_executor(current_executor, tenant)
        await _require_applicant(row, tenant)
        async with get_async_db_session() as active:
            await repository.acheck(active, evidence)
        check_context()
        await service._require_action(
            "folder" if row.parent_folder_id is not None else "knowledge_space",
            row.parent_folder_id if row.parent_folder_id is not None else row.space_id,
            "upload_file",
        )
        check_context()
        if await identity.acapture(executor) != original_identity:
            _deny()
        check_context()

    service._upload_execution_guard = guard
    service.upload_application_factory = lambda: _ApprovedUpload(
        evidence=evidence,
        guard=guard,
        login_user=executor,
        session_factory=get_async_db_session,
        admit_upload=service._require_action,
        make_permission_record=service._new_file_permission_record,
        actor_provider=service._permission_actor,
    )
    await guard()
    files = await service.add_file(
        knowledge_id=row.space_id,
        file_path=list(evidence.paths),
        parent_id=row.parent_folder_id,
        skip_approval=True,
    )
    await guard()
    async with get_async_db_session() as final, final.begin():
        check_context()
        await repository.afinalize(final, evidence, (file.id for file in files))
        check_context()
    check_context()


def get_legacy_upload_finalizer():
    return finalize_approved_upload
