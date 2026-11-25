"""Register one authorized external item and finalize only its own receipt."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import select

from bisheng.knowledge.application.provider_upload_quota import (
    ProviderUploadQuota,
    UploadIdentity,
    forward_provider_stream,
    reconcile_provider_stream,
    validate_chunking,
)
from bisheng.knowledge.domain.models.knowledge_file import FileSource
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderBinding as Binding,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderGeneration as Generation,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderInstance as Instance,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderMapping as Mapping,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderOperation as Op,
)
from bisheng.knowledge.domain.repositories.provider_operation_repository import (
    ProviderOperationRepository,
    RequestKeyConflict,
)
from bisheng.knowledge.domain.repositories.upload_registration_repository import NewUploadFile
from bisheng.knowledge.domain.services.knowledge_processing_guard import require_space_processing_idle


@dataclass(frozen=True, slots=True)
class UploadItemResult:
    """Only stable local identities are visible to the authorized caller."""

    state: str
    operation_id: str
    file_id: int
    version_id: int


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


async def _require_upload_instance(db, scope, cap):
    revision = await db.scalar(
        select(Instance.capability_revision)
        .where(
            Instance.tenant_id == scope.tenant_id,
            Instance.id == scope.instance_id,
            Instance.provider_key == scope.provider_key,
            Instance.remote_scope_id == scope.remote_scope_id,
            Instance.state == "ready",
        )
        .with_for_update()
    )
    if type(cap) is not int or cap <= 0 or revision != cap:
        raise ValueError("upload instance or capability proof changed")


async def _require_upload_target(db, scope, cap):
    binding = await db.scalar(
        select(Binding)
        .where(Binding.tenant_id == scope.tenant_id, Binding.space_id == scope.space_id)
        .with_for_update()
    )
    if (
        binding is None
        or binding.pending_write_operation_id
        or (binding.provider_key, binding.state, binding.active_generation)
        != (scope.provider_key, "ready", scope.generation)
    ):
        raise ValueError("external space not ready for upload")
    target = await db.scalar(
        select(Generation)
        .where(
            Generation.tenant_id == scope.tenant_id,
            Generation.space_id == scope.space_id,
            Generation.generation == scope.generation,
            Generation.state == "ready",
            Generation.provider_instance_id == scope.instance_id,
            Generation.remote_scope_id == scope.remote_scope_id,
            Generation.remote_kb_id == scope.remote_kb_id,
        )
        .with_for_update()
    )
    if target is None:
        raise ValueError("upload target changed")
    await _require_upload_instance(db, scope, cap)


async def upload_item(
    app,
    knowledge,
    parent_id,
    request_key,
    file_name,
    byte_count,
    checksum,
    chunks,
    port,
    user_limit,
    tenant_limit,
    chunking,
):
    """port is startup-owned and binding-scoped, limits are server policy budgets.

    Commit local registration + both reservations + sender claim before first
    byte. A replay can query its original receipt, never resend an unknown write.
    """
    options = validate_chunking(chunking)
    scope = port.context
    tenant, space, user = knowledge.tenant_id, knowledge.id, app.user.user_id
    if (scope.tenant_id, scope.space_id, scope.operation) != (
        tenant,
        space,
        "upload",
    ) or scope.provider_key == "native":
        raise ValueError("invalid upload port")
    # Capability-dependent parameters must be checked before registering files.
    port.validate_upload(options)
    digest = sha256(
        json.dumps(
            [
                user,
                space,
                parent_id,
                file_name,
                byte_count,
                checksum,
                options,
                scope.instance_id,
                scope.generation,
                scope.remote_scope_id,
                scope.remote_kb_id,
            ],
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    ledger, quota = ProviderOperationRepository(), ProviderUploadQuota()
    async with app._session() as db, db.begin():
        await quota.lock_tenant(db, tenant)
        actual = await app.repository.alock_space_for_upload(db, space_id=space)
        require_space_processing_idle(actual, operation="upload_file")
        cap = getattr(port, "capability_revision", None)
        await _require_upload_target(db, scope, cap)
        intent = Op(
            tenant_id=tenant,
            kind="upload",
            request_key=request_key,
            request_hash=digest,
            actor_user_id=user,
            provider_instance_id=scope.instance_id,
            remote_scope_id=scope.remote_scope_id,
            remote_kb_id=scope.remote_kb_id,
            space_id=space,
            generation=scope.generation,
            operation_epoch=1,
            capability_revision=cap,
            phase="upload",
        )
        op = await ledger.accept(db, intent)
        if op is intent:
            (registered,) = await app.repository.aregister_initial(
                db,
                space_id=space,
                parent_id=parent_id,
                files=(
                    NewUploadFile(
                        file_name,
                        byte_count,
                        None,
                        json.dumps(options) if options is not None else None,
                        FileSource.SPACE_UPLOAD.value,
                        {},
                        user,
                        app.user.user_name,
                        user,
                        app.user.user_name,
                    ),
                ),
            )
            file_id, doc_id, version_id = registered.file.id, registered.document_id, registered.version_id
            op.target_manifest = [
                {
                    "file_id": file_id,
                    "document_id": doc_id,
                    "version_id": version_id,
                    "byte_count": byte_count,
                    "sha256": checksum,
                    "parent_id": parent_id,
                }
            ]
        else:
            (facts,) = op.target_manifest
            file_id, doc_id, version_id = facts["file_id"], facts["document_id"], facts["version_id"]
        if op.capability_revision != cap:
            raise RequestKeyConflict("original upload capability revision changed")
        resend = op.state == "failed" and op.last_error_code == "not_received"
        if resend:
            # Tenant lock serializes client retries; the new epoch fences old receipts.
            op.operation_epoch += 1
            op.state, op.last_error_code, op.next_attempt_at = "pending", None, _now()
        key = UploadIdentity(
            tenant,
            user,
            space,
            scope.generation,
            scope.instance_id,
            scope.remote_scope_id,
            scope.remote_kb_id,
            request_key,
            op.operation_id,
            file_id,
            doc_id,
            version_id,
            byte_count,
            checksum,
            op.operation_epoch,
        )

        def item_result(state):
            return UploadItemResult(state, key.operation_id, key.file_id, key.version_id)

        if op.state == "succeeded":
            return item_result("accepted")
        if op.state in ("failed", "manual_review"):
            return item_result("reupload_required" if op.last_error_code == "not_received" else "conflict")
        await quota.reserve(db, key, user_limit=user_limit, tenant_limit=tenant_limit, reopen=resend)
        owner = await ledger.claim(db, tenant_id=tenant, operation_id=op.operation_id, now=_now(), lease_seconds=300)
        if owner is None:
            return item_result("unknown")
        token, revision, state = owner.lease_token, owner.revision, owner.state
        if state == "sending" and op is not intent and not resend:
            raise RequestKeyConflict("prior upload cannot be sent blindly")
    await app._check_identity(tenant)
    if state == "sending":
        # Authorization may have performed IO since registration. Recheck before forwarding.
        async with app._session() as db, db.begin():
            await _require_upload_target(db, scope, cap)
        result = await forward_provider_stream(key, chunks, options, port.send, port.lookup)
    else:
        result = await reconcile_provider_stream(key, port.lookup)
    if result.state == "accepted":
        # Projection is idempotent and cannot expose content: the mapping is
        # not published until the following transaction. No ready proof here.
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
        from bisheng.permission.application.access import get_f048_resource_adapter

        async with app._session() as db, db.begin():
            row = await db.scalar(
                select(KnowledgeFile).where(
                    KnowledgeFile.id == file_id, KnowledgeFile.tenant_id == tenant, KnowledgeFile.knowledge_id == space
                )
            )
            if row is None:
                raise ValueError("registered upload no longer present")
            record = app.make_record(
                row=row,
                resource_type="knowledge_file",
                parent_type="folder" if parent_id is not None else "knowledge_space",
                parent_id=parent_id or space,
            )
        actor = await app._check_identity(tenant)
        await (await get_f048_resource_adapter("knowledge_file")).authorize_created(record=record, actor=actor)
    await app._check_identity(tenant)
    async with app._session() as db, db.begin():
        await quota.lock_tenant(db, tenant)

        async def advance(state, error=None):
            return await ledger.apply(
                db,
                tenant_id=tenant,
                operation_id=key.operation_id,
                lease_token=token,
                expected_revision=revision,
                generation=key.generation,
                operation_epoch=key.operation_epoch,
                now=_now(),
                state=state,
                last_error_code=error,
            )

        if result.state == "accepted":
            # A conflict response may carry another directory's object. Never adopt it,
            # and never propagate an IntegrityError containing the provider identifier.
            existing = await db.scalar(
                select(Mapping.id)
                .where(
                    Mapping.tenant_id == tenant,
                    Mapping.space_id == space,
                    Mapping.generation == key.generation,
                    Mapping.resource_type == "file",
                    Mapping.remote_object_id == result.remote_id,
                )
                .with_for_update()
            )
            if existing is not None:
                return item_result("conflict" if await advance("manual_review") else "unknown")
            if not await advance("applying"):
                return item_result("unknown")
            owner = await ledger.claim(
                db, tenant_id=tenant, operation_id=key.operation_id, now=_now(), lease_seconds=30
            )
            token, revision = owner.lease_token, owner.revision
            await quota.verify(db, key)
            db.add(
                Mapping(
                    tenant_id=tenant,
                    space_id=space,
                    generation=scope.generation,
                    resource_type="file",
                    local_resource_id=file_id,
                    logical_document_id=doc_id,
                    version_id=version_id,
                    remote_object_id=result.remote_id,
                    lifecycle_state="received",
                    operation_epoch=key.operation_epoch,
                )
            )
            if not await advance("succeeded"):
                raise ValueError("upload finalization lost its lease")
        elif result.state == "reupload_required":
            if not await advance("failed", "not_received"):
                return item_result("unknown")
            await quota.release(db, key)
        elif not await advance("manual_review" if result.state == "conflict" else "reconciling"):
            return item_result("unknown")
    # Never expose provider identifiers to the upload caller.
    return item_result(result.state)
