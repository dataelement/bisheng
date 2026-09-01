from __future__ import annotations

from types import SimpleNamespace

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.filelib_sync import FilelibSyncPermissionDeniedError
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.developer_token.domain.models import DeveloperToken
from bisheng.developer_token.domain.schemas import DeveloperTokenFileSyncRule
from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (
    KnowledgeDocumentDistributionService,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.open_endpoints.domain.repositories.implementations.filelib_sync_repository_impl import (
    FilelibSyncRepositoryImpl,
)
from bisheng.open_endpoints.domain.services.filelib_sync_factory import (
    build_filelib_sync_service_for_scheduled_sync,
)
from bisheng.open_endpoints.domain.services.filelib_sync_service import FilelibSyncService


@pytest.fixture(autouse=True)
def _skip_fulltext_tracker(monkeypatch):
    monkeypatch.setattr(
        "bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl.track_fulltext_file_changes",
        lambda _session: None,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_document_distribution_service.track_fulltext_file_changes",
        lambda _session: None,
    )


def _session() -> SimpleNamespace:
    return SimpleNamespace()


def _rule() -> DeveloperTokenFileSyncRule:
    return DeveloperTokenFileSyncRule.model_validate(
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "fixed", "code": "IT"},
            "target_space": {"mode": "fixed", "knowledge_id": 8, "folder_mode": "none"},
        }
    )


def test_build_filelib_sync_service_for_scheduled_sync():
    session = _session()
    token = DeveloperToken(
        id=7,
        tenant_id=5,
        user_id=100,
        name="scheduled-token",
        token_hash="hash",
        token_ciphertext="cipher",
        token_prefix="bs_abc",
        enabled=True,
    )
    login_user = UserPayload(user_id=100, user_name="token-user", tenant_id=5)
    rule = _rule()

    service = build_filelib_sync_service_for_scheduled_sync(
        session=session,
        token=token,
        file_sync_rule=rule,
        login_user=login_user,
    )

    assert isinstance(service, FilelibSyncService)
    assert service.request is None
    assert service.token_id == 7
    assert service.token_name == "scheduled-token"
    assert service.file_sync_rule == rule
    assert isinstance(service.repository, FilelibSyncRepositoryImpl)
    assert isinstance(service.knowledge_space_service, KnowledgeSpaceService)
    assert service.knowledge_space_service.request is None
    assert service.knowledge_space_service.login_user is login_user
    assert isinstance(
        service.knowledge_space_service.document_distribution_service,
        KnowledgeDocumentDistributionService,
    )


@pytest.mark.asyncio
async def test_scheduled_sync_factory_service_surfaces_upload_permission_errors(monkeypatch):
    session = _session()
    token = DeveloperToken(
        id=7,
        tenant_id=5,
        user_id=100,
        name="scheduled-token",
        token_hash="hash",
        token_ciphertext="cipher",
        token_prefix="bs_abc",
        enabled=True,
    )
    login_user = UserPayload(user_id=100, user_name="token-user", tenant_id=5)
    service = build_filelib_sync_service_for_scheduled_sync(
        session=session,
        token=token,
        file_sync_rule=_rule(),
        login_user=login_user,
    )

    async def _deny_upload(*args, **kwargs):
        raise SpacePermissionDeniedError()

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService.validate_file_sync_target",
        _deny_upload,
    )

    with pytest.raises(FilelibSyncPermissionDeniedError, match="no upload permission"):
        await service._require_upload_permission(
            SimpleNamespace(
                space=SimpleNamespace(id=8),
                folder_id=None,
                used_personal_fallback=False,
                used_responsible_person_personal=False,
            )
        )
