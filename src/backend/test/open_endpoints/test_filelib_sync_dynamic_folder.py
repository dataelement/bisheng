from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.filelib_sync import FilelibSyncNotFoundError
from bisheng.developer_token.domain.schemas import DeveloperTokenFileSyncRule
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.open_endpoints.domain.services.filelib_sync_service import (
    FilelibSyncService,
    ResolvedFileSyncTarget,
    ResolvedIdentity,
)


def _rule(**target_space_overrides) -> DeveloperTokenFileSyncRule:
    target_space = {
        "mode": "fixed",
        "knowledge_id": 8,
        "folder_id": None,
        "dynamic_source": None,
        "folder_mode": "none",
        "folder_path": None,
        "parent_folder_path": None,
        "folder_dynamic_source": None,
    }
    target_space.update(target_space_overrides)
    return DeveloperTokenFileSyncRule.model_validate(
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "fixed", "code": "IT"},
            "target_space": target_space,
        }
    )


def _identity(**overrides) -> ResolvedIdentity:
    defaults = {
        "responsible_user_id": 7,
        "responsible_user_name": "bound",
        "responsible_user_external_id": "bound-ext",
        "responsible_department": SimpleNamespace(id=21, name="责任部门"),
        "caller_department": SimpleNamespace(id=30, name="绑定用户主责部门"),
        "main_department": SimpleNamespace(id=20, name="同步部门"),
        "business_domain_department": None,
        "target_space_department": None,
    }
    defaults.update(overrides)
    return ResolvedIdentity(**defaults)


def _service(rule: DeveloperTokenFileSyncRule, knowledge_space_service=None) -> FilelibSyncService:
    return FilelibSyncService(
        request=SimpleNamespace(headers={}),
        login_user=UserPayload(user_id=7, user_name="bound", user_role=[2], tenant_id=5),
        token_id=42,
        file_sync_rule=rule,
        repository=SimpleNamespace(),
        knowledge_space_service=knowledge_space_service or SimpleNamespace(),
    )


@pytest.mark.asyncio
async def test_fixed_folder_mode_resolves_string_path() -> None:
    created = KnowledgeFile(id=5001, knowledge_id=8, file_name="管理制度", file_type=0)
    knowledge_space_service = SimpleNamespace(
        find_or_create_folder_path_for_file_sync=AsyncMock(return_value=created),
    )
    service = _service(
        _rule(folder_mode="fixed", folder_path="政策文件/管理制度"),
        knowledge_space_service=knowledge_space_service,
    )

    folder_id = await service._resolve_target_folder(8, _identity())

    assert folder_id == 5001
    knowledge_space_service.find_or_create_folder_path_for_file_sync.assert_awaited_once_with(
        8,
        "政策文件/管理制度",
    )


@pytest.mark.asyncio
async def test_dynamic_folder_mode_uses_parent_path_and_department_name() -> None:
    parent = KnowledgeFile(id=4096, knowledge_id=8, file_name="政策文件", file_type=0)
    created = KnowledgeFile(id=5001, knowledge_id=8, file_name="同步部门", file_type=0)
    knowledge_space_service = SimpleNamespace(
        find_or_create_folder_path_for_file_sync=AsyncMock(return_value=parent),
        find_or_create_folder_for_file_sync=AsyncMock(return_value=created),
    )
    service = _service(
        _rule(
            folder_mode="dynamic",
            folder_dynamic_source="department_name",
            parent_folder_path="政策文件",
        ),
        knowledge_space_service=knowledge_space_service,
    )

    folder_id = await service._resolve_target_folder(8, _identity())

    assert folder_id == 5001
    knowledge_space_service.find_or_create_folder_path_for_file_sync.assert_awaited_once_with(
        8,
        "政策文件",
    )
    knowledge_space_service.find_or_create_folder_for_file_sync.assert_awaited_once_with(
        8,
        "同步部门",
        4096,
    )


@pytest.mark.asyncio
async def test_dynamic_folder_mode_uses_caller_main_department_name_at_root() -> None:
    created = KnowledgeFile(id=5002, knowledge_id=8, file_name="绑定用户主责部门", file_type=0)
    knowledge_space_service = SimpleNamespace(
        find_or_create_folder_path_for_file_sync=AsyncMock(return_value=None),
        find_or_create_folder_for_file_sync=AsyncMock(return_value=created),
    )
    service = _service(
        _rule(
            folder_mode="dynamic",
            folder_dynamic_source="caller_main_department_name",
        ),
        knowledge_space_service=knowledge_space_service,
    )

    folder_id = await service._resolve_target_folder(8, _identity())

    assert folder_id == 5002
    knowledge_space_service.find_or_create_folder_for_file_sync.assert_awaited_once_with(
        8,
        "绑定用户主责部门",
        None,
    )


@pytest.mark.asyncio
async def test_dynamic_target_with_dynamic_folder_resolves_space_then_child_folder() -> None:
    space = Knowledge(id=8, name="信息库", type=3, business_domain_codes=["IT"])
    created = KnowledgeFile(id=5003, knowledge_id=8, file_name="同步部门", file_type=0)
    knowledge_space_service = SimpleNamespace(
        find_or_create_folder_path_for_file_sync=AsyncMock(return_value=None),
        find_or_create_folder_for_file_sync=AsyncMock(return_value=created),
    )
    service = _service(
        DeveloperTokenFileSyncRule.model_validate(
            {
                "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
                "business_domain": {"mode": "fixed", "code": "IT"},
                "target_space": {
                    "mode": "dynamic",
                    "knowledge_id": None,
                    "dynamic_source": "department_id",
                    "folder_mode": "dynamic",
                    "folder_dynamic_source": "department_name",
                },
            }
        ),
        knowledge_space_service=knowledge_space_service,
    )
    service._find_department_space = AsyncMock(return_value=space)
    identity = _identity(target_space_department=SimpleNamespace(id=20, name="同步部门"))

    target = await service._resolve_target_space(identity)
    folder_id = await service._resolve_target_folder(int(target.space.id), identity)

    assert target == ResolvedFileSyncTarget(space=space, folder_id=None)
    assert folder_id == 5003


@pytest.mark.asyncio
async def test_dynamic_folder_department_name_follows_responsible_person_main_department() -> None:
    caller_department = SimpleNamespace(id=30, name="临时访客")
    responsible_department = SimpleNamespace(id=20, name="测试111")
    created = KnowledgeFile(id=5004, knowledge_id=8, file_name="测试111", file_type=0)
    knowledge_space_service = SimpleNamespace(
        find_or_create_folder_path_for_file_sync=AsyncMock(return_value=None),
        find_or_create_folder_for_file_sync=AsyncMock(return_value=created),
    )
    service = _service(
        _rule(
            folder_mode="dynamic",
            folder_dynamic_source="department_name",
        ),
        knowledge_space_service=knowledge_space_service,
    )
    identity = _identity(
        caller_department=caller_department,
        responsible_department=responsible_department,
        main_department=responsible_department,
    )

    folder_id = await service._resolve_target_folder(8, identity)

    assert folder_id == 5004
    knowledge_space_service.find_or_create_folder_for_file_sync.assert_awaited_once_with(
        8,
        "测试111",
        None,
    )


@pytest.mark.asyncio
async def test_legacy_folder_id_still_works_when_folder_path_missing() -> None:
    service = _service(_rule(folder_mode="fixed", folder_id=4096))

    folder_id = await service._resolve_target_folder(8, _identity())

    assert folder_id == 4096
