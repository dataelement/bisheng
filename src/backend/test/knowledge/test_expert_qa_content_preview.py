"""专家问答上下文放行后, 文档入口预览不再被部门权限打断."""

from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.knowledge.domain.schemas.knowledge_document_distribution_schema import (
    KnowledgeDocumentEntryCapabilities,
    ResolvedKnowledgeDocumentEntry,
)
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileAccessDecision,
    DepartmentFileAccessSource,
    DepartmentFileAccessStatus,
)
from bisheng.knowledge.domain.services.expert_qa_content_preview import (
    grant_expert_qa_content_preview,
)


def _resolved(*, can_download: bool = False) -> ResolvedKnowledgeDocumentEntry:
    return ResolvedKnowledgeDocumentEntry(
        tenant_id=1,
        requested_space_id=12,
        entry_file_id=88,
        entry_type="manager",
        content_file_id=88,
        manager_file_id=88,
        manager_space_id=12,
        capabilities=KnowledgeDocumentEntryCapabilities(can_download=can_download),
    )


def _qa_decision() -> DepartmentFileAccessDecision:
    return DepartmentFileAccessDecision(
        file_id=88,
        space_id=12,
        status=DepartmentFileAccessStatus.ALLOWED,
        source=DepartmentFileAccessSource.EXPERT_QA,
        can_download=False,
    )


def test_grant_allows_preview_and_keeps_download_off():
    granted = grant_expert_qa_content_preview(_resolved(), _qa_decision(), "can_preview")
    assert granted is not None
    assert granted.capabilities.can_view is True
    assert granted.capabilities.can_preview is True
    assert granted.capabilities.can_download is False


def test_grant_ignores_download_capability():
    assert grant_expert_qa_content_preview(_resolved(), _qa_decision(), "can_download") is None


def test_grant_ignores_non_qa_decision():
    decision = DepartmentFileAccessDecision(
        file_id=88,
        space_id=12,
        status=DepartmentFileAccessStatus.ALLOWED,
        source=DepartmentFileAccessSource.PERMISSION_TEMPLATE,
    )
    assert grant_expert_qa_content_preview(_resolved(), decision, "can_preview") is None


def _load_service_class():
    if "bisheng.common.services.base" not in sys.modules:
        base_service_stub = types.ModuleType("bisheng.common.services.base")
        base_service_stub.BaseService = type("BaseService", (), {})
        sys.modules["bisheng.common.services.base"] = base_service_stub
    module = importlib.import_module("bisheng.knowledge.domain.services.knowledge_space_service")
    return module.KnowledgeSpaceService


@pytest.mark.asyncio
async def test_content_entry_uses_expert_qa_grant_before_department_deny():
    service = _load_service_class()(MagicMock(), SimpleNamespace(user_id=9, tenant_id=1))
    file_record = SimpleNamespace(id=88, knowledge_id=12)
    service._portal_file_access_decision_map[88] = _qa_decision()
    service._resolve_document_entry = AsyncMock(return_value=_resolved())
    service.department_file_view_access_service = SimpleNamespace(
        evaluate_file=AsyncMock(side_effect=AssertionError("不应再查部门文件权限")),
    )

    resolved = await service._resolve_shougang_portal_content_entry(
        file_record,
        required_capability="can_preview",
    )

    assert resolved.capabilities.can_preview is True
    assert resolved.capabilities.can_download is False


@pytest.mark.asyncio
async def test_content_entry_still_denies_download_under_expert_qa_grant():
    service = _load_service_class()(MagicMock(), SimpleNamespace(user_id=9, tenant_id=1))
    file_record = SimpleNamespace(id=88, knowledge_id=12)
    service._portal_file_access_decision_map[88] = _qa_decision()
    service._resolve_document_entry = AsyncMock(return_value=_resolved())

    with pytest.raises(SpacePermissionDeniedError):
        await service._resolve_shougang_portal_content_entry(
            file_record,
            required_capability="can_download",
        )
