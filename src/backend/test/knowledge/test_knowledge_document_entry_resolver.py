"""Security and capability contracts for the F059 entry resolvers."""

from __future__ import annotations

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import (
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_document_entry_resolver import (
    KnowledgeDocumentDurableReferenceResolver,
    KnowledgeDocumentEntryResolutionError,
    KnowledgeDocumentEntryResolver,
)

ALL_PERMISSIONS = {
    "view_file",
    "download_file",
    "move_file",
    "manage_file_relation",
    "rename_file",
    "publish_file",
    "share_file",
    "delete_file",
}


async def _all_permissions(_file_id: int, _space_id: int) -> set[str]:
    return set(ALL_PERMISSIONS)


async def _seed_distribution(async_db_session: AsyncSession) -> None:
    async_db_session.add_all(
        [
            KnowledgeDocument(
                id=91,
                tenant_id=7,
                knowledge_id=20,
                primary_version_id=501,
                content_generation=4,
            ),
            KnowledgeFile(
                id=99,
                tenant_id=7,
                knowledge_id=10,
                file_name="old.pdf",
                object_name="tenant/7/old.pdf",
            ),
            KnowledgeFile(
                id=100,
                tenant_id=7,
                knowledge_id=20,
                file_name="canonical.pdf",
                object_name="tenant/7/canonical.pdf",
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.MANAGER.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                projection_status=KnowledgeFileProjectionStatus.READY.value,
                desired_content_generation=4,
                applied_content_generation=4,
            ),
            KnowledgeFile(
                id=101,
                tenant_id=7,
                knowledge_id=10,
                file_name="canonical.pdf",
                file_size=0,
                object_name=None,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.PUBLISH.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                projection_status=KnowledgeFileProjectionStatus.READY.value,
                desired_content_generation=4,
                applied_content_generation=4,
            ),
            KnowledgeFile(
                id=102,
                tenant_id=7,
                knowledge_id=30,
                file_name="canonical.pdf",
                file_size=0,
                object_name=None,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.SHARE.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                allow_download=False,
                projection_status=KnowledgeFileProjectionStatus.PENDING.value,
                desired_content_generation=4,
            ),
            KnowledgeDocumentVersion(
                id=500,
                document_id=91,
                knowledge_file_id=99,
                version_no=1,
                is_primary=False,
            ),
            KnowledgeDocumentVersion(
                id=501,
                document_id=91,
                knowledge_file_id=100,
                version_no=2,
                is_primary=True,
            ),
        ]
    )
    await async_db_session.commit()


async def _seed_ordinary_primary(
    async_db_session: AsyncSession,
    *,
    include_document: bool = True,
    document_tenant_id: int = 7,
    document_space_id: int = 10,
) -> None:
    rows = [
        KnowledgeFile(
            id=103,
            tenant_id=7,
            knowledge_id=10,
            file_name="ordinary.pdf",
            object_name="tenant/7/ordinary.pdf",
        ),
        KnowledgeDocumentVersion(
            id=502,
            document_id=92,
            knowledge_file_id=103,
            version_no=1,
            is_primary=True,
        ),
    ]
    if include_document:
        rows.insert(
            0,
            KnowledgeDocument(
                id=92,
                tenant_id=document_tenant_id,
                knowledge_id=document_space_id,
                primary_version_id=502,
            ),
        )
    async_db_session.add_all(rows)
    await async_db_session.commit()


def _resolver(
    async_db_session: AsyncSession,
    permission_loader=_all_permissions,
) -> KnowledgeDocumentEntryResolver:
    return KnowledgeDocumentEntryResolver(
        document_repository=KnowledgeDocumentRepositoryImpl(async_db_session),
        version_repository=KnowledgeDocumentVersionRepositoryImpl(
            async_db_session
        ),
        file_repository=KnowledgeFileRepositoryImpl(async_db_session),
        permission_loader=permission_loader,
    )


@pytest.mark.asyncio
async def test_manager_resolution_uses_primary_version_as_authority(
    async_db_session: AsyncSession,
):
    await _seed_distribution(async_db_session)

    resolved = await _resolver(async_db_session).resolve(
        tenant_id=7,
        space_id=20,
        file_id=100,
    )

    assert resolved.entry_type == "manager"
    assert resolved.canonical_document_id == 91
    assert resolved.canonical_version_id == 501
    assert resolved.content_file_id == 100
    assert resolved.manager_file_id == 100
    assert resolved.manager_space_id == 20
    assert resolved.projection_ready is True
    assert resolved.capabilities.can_edit_content is True
    assert resolved.capabilities.can_publish is True
    assert resolved.capabilities.can_share is True
    assert resolved.capabilities.can_delete is True


@pytest.mark.asyncio
async def test_publish_and_share_hard_constraints_override_granted_permissions(
    async_db_session: AsyncSession,
):
    await _seed_distribution(async_db_session)
    resolver = _resolver(async_db_session)

    publish = await resolver.resolve(tenant_id=7, space_id=10, file_id=101)
    share = await resolver.resolve(tenant_id=7, space_id=30, file_id=102)

    assert publish.capabilities.can_edit_content is False
    assert publish.capabilities.can_delete is False
    assert publish.capabilities.can_publish is False
    assert publish.capabilities.can_share is True

    assert share.capabilities.can_edit_content is False
    assert share.capabilities.can_publish is False
    assert share.capabilities.can_share is False
    assert share.capabilities.can_download is False
    assert share.capabilities.can_delete is True
    assert share.projection_ready is False


@pytest.mark.asyncio
async def test_resolution_rejects_cross_space_cross_tenant_and_hidden_states(
    async_db_session: AsyncSession,
):
    await _seed_distribution(async_db_session)
    resolver = _resolver(async_db_session)

    with pytest.raises(KnowledgeDocumentEntryResolutionError, match="space"):
        await resolver.resolve(tenant_id=7, space_id=20, file_id=101)
    with pytest.raises(KnowledgeDocumentEntryResolutionError, match="tenant"):
        await resolver.resolve(tenant_id=8, space_id=10, file_id=101)

    share = await KnowledgeFileRepositoryImpl(async_db_session).find_by_id(102)
    share.entry_status = KnowledgeFileEntryStatus.DELETING.value
    async_db_session.add(share)
    await async_db_session.commit()

    with pytest.raises(KnowledgeDocumentEntryResolutionError, match="active"):
        await resolver.resolve(tenant_id=7, space_id=30, file_id=102)


@pytest.mark.asyncio
async def test_historical_physical_id_is_not_an_ordinary_access_entry(
    async_db_session: AsyncSession,
):
    await _seed_distribution(async_db_session)

    with pytest.raises(
        KnowledgeDocumentEntryResolutionError,
        match="historical",
    ):
        await _resolver(async_db_session).resolve(
            tenant_id=7,
            space_id=10,
            file_id=99,
        )


@pytest.mark.asyncio
async def test_durable_reference_selects_requested_active_entry_and_rechecks_permission(
    async_db_session: AsyncSession,
):
    await _seed_distribution(async_db_session)

    async def permission_loader(file_id: int, _space_id: int) -> set[str]:
        return {"view_file"} if file_id == 101 else set()

    entry_resolver = _resolver(async_db_session, permission_loader)
    durable_resolver = KnowledgeDocumentDurableReferenceResolver(
        entry_resolver=entry_resolver,
        version_repository=KnowledgeDocumentVersionRepositoryImpl(
            async_db_session
        ),
        file_repository=KnowledgeFileRepositoryImpl(async_db_session),
    )

    resolved = await durable_resolver.resolve(
        tenant_id=7,
        requested_space_id=10,
        durable_file_id=99,
    )
    assert resolved.entry_file_id == 101
    assert resolved.capabilities.can_view is True

    with pytest.raises(KnowledgeDocumentEntryResolutionError, match="authorized"):
        await durable_resolver.resolve(
            tenant_id=7,
            requested_space_id=30,
            durable_file_id=99,
        )

    externally_authorized = await durable_resolver.resolve(
        tenant_id=7,
        requested_space_id=30,
        durable_file_id=99,
        require_view_permission=False,
    )
    assert externally_authorized.entry_file_id == 102
    assert externally_authorized.capabilities.can_view is False


@pytest.mark.asyncio
async def test_durable_reference_resolves_ordinary_primary_without_distribution(
    async_db_session: AsyncSession,
):
    await _seed_ordinary_primary(async_db_session)
    entry_resolver = _resolver(async_db_session)
    durable_resolver = KnowledgeDocumentDurableReferenceResolver(
        entry_resolver=entry_resolver,
        version_repository=KnowledgeDocumentVersionRepositoryImpl(
            async_db_session
        ),
        file_repository=KnowledgeFileRepositoryImpl(async_db_session),
    )

    resolved = await durable_resolver.resolve(
        tenant_id=7,
        requested_space_id=10,
        durable_file_id=103,
    )

    assert resolved.entry_type == "normal"
    assert resolved.entry_file_id == 103
    assert resolved.content_file_id == 103
    assert resolved.capabilities.can_view is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("include_document", "document_tenant_id", "document_space_id", "error"),
    [
        (False, 7, 10, "does not exist"),
        (True, 8, 10, "tenant"),
        (True, 7, 20, "space"),
    ],
)
async def test_ordinary_version_rejects_invalid_document_identity(
    async_db_session: AsyncSession,
    include_document: bool,
    document_tenant_id: int,
    document_space_id: int,
    error: str,
):
    await _seed_ordinary_primary(
        async_db_session,
        include_document=include_document,
        document_tenant_id=document_tenant_id,
        document_space_id=document_space_id,
    )

    with pytest.raises(KnowledgeDocumentEntryResolutionError, match=error):
        await _resolver(async_db_session).resolve(
            tenant_id=7,
            space_id=10,
            file_id=103,
        )
