"""F059 知识空间创建数量不限量回归测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


class _CreateReached(RuntimeError):
    """证明创建链路已越过历史数量校验并到达持久化边界。"""


@pytest.fixture
def unlimited_space_service(monkeypatch):
    from bisheng.knowledge.domain.models.knowledge_space_scope import (
        KnowledgeSpaceLevelEnum,
        KnowledgeSpaceOwnerTypeEnum,
    )
    from bisheng.knowledge.domain.services import knowledge_space_service as service_module

    login_user = SimpleNamespace(
        user_id=11,
        user_name="申请人",
        tenant_id=1,
        is_admin=lambda: True,
    )
    service = service_module.KnowledgeSpaceService(
        request=SimpleNamespace(),
        login_user=login_user,
    )

    count_spaces = AsyncMock(side_effect=AssertionError("knowledge-space count must not be read"))
    monkeypatch.setattr(service_module.KnowledgeDao, "async_count_spaces_by_user", count_spaces)
    monkeypatch.setattr(
        service_module.LLMService,
        "get_workbench_llm",
        AsyncMock(return_value=SimpleNamespace(embedding_model=SimpleNamespace(id=7))),
    )
    monkeypatch.setattr(
        service,
        "_resolve_space_scope_on_create",
        AsyncMock(
            return_value=(
                KnowledgeSpaceLevelEnum.TEAM,
                KnowledgeSpaceOwnerTypeEnum.USER,
                login_user.user_id,
            )
        ),
    )
    monkeypatch.setattr(service, "_ensure_space_name_unique_in_scope", AsyncMock(return_value=None))
    monkeypatch.setattr(
        service_module.KnowledgeService,
        "acreate_knowledge_base",
        AsyncMock(side_effect=_CreateReached("create persistence reached")),
    )
    return service, count_spaces


async def test_validate_create_does_not_read_user_space_count(unlimited_space_service):
    service, count_spaces = unlimited_space_service

    result = await service.validate_knowledge_space_create(
        name="第 201 个知识空间",
        space_level="team",
        auto_tag_custom_tags=["测试标签"],
    )

    assert result[0].value == "team"
    count_spaces.assert_not_awaited()


async def test_create_does_not_read_user_space_count(unlimited_space_service):
    service, count_spaces = unlimited_space_service

    with pytest.raises(_CreateReached, match="create persistence reached"):
        await service.create_knowledge_space(
            name="第 201 个知识空间",
            space_level="team",
            auto_tag_custom_tags=["测试标签"],
        )

    count_spaces.assert_not_awaited()


async def test_shougang_direct_submit_reuses_unlimited_service(unlimited_space_service, monkeypatch):
    from bisheng.approval.domain.schemas.shougang_approval_schema import (
        ShougangKnowledgeSpaceCreateSubmitReq,
    )
    from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService

    service, count_spaces = unlimited_space_service
    approval_service = ShougangApprovalService()
    monkeypatch.setattr(
        approval_service,
        "_requires_create_approval",
        AsyncMock(return_value=False),
    )

    with pytest.raises(_CreateReached, match="create persistence reached"):
        await approval_service.submit_knowledge_space_create(
            req=ShougangKnowledgeSpaceCreateSubmitReq(
                name="门户第 201 个知识空间",
                space_level="team",
                auto_tag_custom_tags=["测试标签"],
            ),
            login_user=service.login_user,
            space_service=service,
        )

    count_spaces.assert_not_awaited()


async def test_approval_handler_revalidates_with_unlimited_service(unlimited_space_service, monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_handler import (
        KnowledgeSpaceCreateApprovalHandler,
    )
    from bisheng.knowledge.domain.services import knowledge_space_service as service_module

    service, count_spaces = unlimited_space_service
    handler = KnowledgeSpaceCreateApprovalHandler()
    monkeypatch.setattr(handler, "_find_created_space", AsyncMock(return_value=None))
    monkeypatch.setattr(
        handler,
        "_ensure_admin_only_level_applicant_is_admin",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(service_module, "KnowledgeSpaceService", lambda *args, **kwargs: service)

    with pytest.raises(_CreateReached, match="create persistence reached"):
        await handler.on_approved(
            101,
            {
                "tenant_id": 1,
                "applicant_user_id": 11,
                "applicant_user_name": "申请人",
                "create_params": {
                    "name": "审批第 201 个知识空间",
                    "space_level": "team",
                    "auto_tag_custom_tags": ["测试标签"],
                },
            },
        )

    count_spaces.assert_not_awaited()
