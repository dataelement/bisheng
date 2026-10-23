"""接口同步单元测试可显式使用的新组织查询替身。"""

from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.services.knowledge_file_organization_service import KnowledgeFileOrganizationService


@pytest.fixture
def stub_file_organization_lookup(monkeypatch):
    lookup = AsyncMock(return_value=81)
    monkeypatch.setattr(KnowledgeFileOrganizationService, "uploader_organization", lookup)
    return lookup
