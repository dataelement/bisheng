"""A folder grant authorizes its subtree without granting the whole space."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.knowledge_space import SpaceFolderNotFoundError, SpacePermissionDeniedError
from bisheng.core.context.tenant import current_tenant_id
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType
from bisheng.knowledge.domain.services import knowledge_space_service as module
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.permission.test_f048_authorization_model import ModelEvaluator, build_authorization_model_f048


@pytest.fixture
def folder_access(monkeypatch):
    operator = SimpleNamespace(user_id=150028, tenant_id=1, is_global_super=False)
    service = module.KnowledgeSpaceService(request=None, login_user=operator)
    actor = PermissionActor(subject_type="service_account", subject_id=2, tenant_id=1)
    space = SimpleNamespace(id=137, type=KnowledgeTypeEnum.SPACE.value, tenant_id=1)
    folder = SimpleNamespace(id=742, knowledge_id=137, file_type=FileType.DIR.value, file_level_path="")
    decisions = []

    async def check(login_user, *, resource_type, resource_id, action, actor):
        assert login_user is operator
        assert actor.fga_subject == "service_account:2"
        decisions.append((resource_type, resource_id, action))
        return resource_type == "folder" and resource_id == 742 and action in {"visible", "upload_file"}

    monkeypatch.setattr(module, "resolve_permission_actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(module, "check_business_action", check)
    monkeypatch.setattr(module.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=space))
    monkeypatch.setattr(module.KnowledgeFileDao, "query_by_id", AsyncMock(return_value=folder))
    monkeypatch.setattr(module.SpaceFileDao, "get_children_by_prefix", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "_scan_visible_child_items", AsyncMock(return_value=([], False, None)))
    monkeypatch.setattr(service, "_enrich_with_version_info", AsyncMock())
    monkeypatch.setattr(service, "_handle_file_folder_extra_info", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "_get_file_change_excluded_ids", AsyncMock(return_value=set()))
    tenant_token = current_tenant_id.set(1)
    try:
        yield service, folder, decisions
    finally:
        current_tenant_id.reset(tenant_token)


@pytest.mark.parametrize("method", ["list_space_children", "asearch_space_children_cursor"])
async def test_folder_can_be_listed_without_space_grant(folder_access, method):
    service, _, decisions = folder_access

    page = await getattr(service, method)(137, parent_id=742)

    assert page.data == []
    assert decisions == [("folder", 742, "visible")]
    assert await service.can_write_space_container(137, 742)
    assert not await service.can_write_space_container(137)


@pytest.mark.parametrize("method", ["list_space_children", "asearch_space_children_cursor"])
async def test_folder_grant_does_not_allow_root_listing(folder_access, method):
    service, _, decisions = folder_access

    with pytest.raises(SpacePermissionDeniedError):
        await getattr(service, method)(137)

    assert decisions == [("knowledge_space", 137, "visible")]
    service._scan_visible_child_items.assert_not_awaited()


@pytest.mark.parametrize("method", ["list_space_children", "asearch_space_children_cursor"])
async def test_ungranted_folder_is_denied_before_scanning(folder_access, method):
    service, folder, decisions = folder_access
    folder.id = 743

    with pytest.raises(SpacePermissionDeniedError):
        await getattr(service, method)(137, parent_id=743)

    assert decisions == [("folder", 743, "visible")]
    service._scan_visible_child_items.assert_not_awaited()


@pytest.mark.parametrize("method", ["list_space_children", "asearch_space_children_cursor"])
@pytest.mark.parametrize("invalid_field", ["knowledge_id", "file_type"])
async def test_folder_scope_is_validated_before_authorization(folder_access, method, invalid_field):
    service, folder, decisions = folder_access
    setattr(folder, invalid_field, 999)

    with pytest.raises(SpaceFolderNotFoundError):
        await getattr(service, method)(137, parent_id=742)

    assert decisions == []
    service._scan_visible_child_items.assert_not_awaited()


@pytest.mark.parametrize("excluded_ids", [set(), {783}])
async def test_v2_list_returns_inherited_children_and_filters_custom_children(folder_access, monkeypatch, excluded_ids):
    from bisheng.open_endpoints.api.endpoints import filelib

    service, _, _ = folder_access
    children = [
        module.KnowledgeFile(
            id=file_id,
            knowledge_id=137,
            file_name=name,
            file_type=file_type,
            file_level_path="/742",
            status=2,
        )
        for file_id, name, file_type in (
            (745, "inherited-folder", FileType.DIR.value),
            (900, "custom-folder", FileType.DIR.value),
            (783, "inherited.txt", FileType.FILE.value),
        )
    ]
    evaluator = ModelEvaluator(
        build_authorization_model_f048(),
        {
            ("service_account:2", "visible", "folder:742"),
            ("folder:742", "parent", "folder:745"),
            ("folder:742", "parent", "folder:900"),
            ("folder:742", "parent", "knowledge_file:783"),
            ("service_account:*", "inherit_mode", "folder:745"),
            ("service_account:*", "custom_mode", "folder:900"),
            ("service_account:*", "inherit_mode", "knowledge_file:783"),
        },
    )

    async def resolve_targets(*, rows, knowledge, actor, action):
        assert knowledge.id == 137
        assert actor.fga_subject == "service_account:2"
        assert action == "visible"
        return [
            SimpleNamespace(
                resource_type="folder" if row.file_type == FileType.DIR.value else "knowledge_file",
                resource_id=str(row.id),
            )
            for row in rows
        ]

    async def check_visible(*, actor, targets):
        return {
            (target.resource_type, target.resource_id): evaluator.check(
                actor.fga_subject, "visible", f"{target.resource_type}:{target.resource_id}"
            )
            for target in targets
        }

    async def enrich(rows, *, file_change_excluded_ids, space_creator_user_id=None):
        # space_creator_user_id arrived with the space-children read optimisation:
        # the folder rollup reports 存在异常 to the space creator only. This test is
        # about the file-change exclusion, so it just has to accept the argument.
        del space_creator_user_id
        assert file_change_excluded_ids == excluded_ids
        return [{"id": row.id} for row in rows]

    monkeypatch.setattr(filelib, "get_open_api_operator_async", AsyncMock(return_value=service.login_user))
    monkeypatch.setattr(filelib, "_build_space_service", lambda *args: service)
    monkeypatch.setattr(
        service, "_scan_visible_child_items", module.KnowledgeSpaceService._scan_visible_child_items.__get__(service)
    )
    monkeypatch.setattr(
        service,
        "_resource_adapter",
        AsyncMock(
            return_value=SimpleNamespace(
                resolve_permission_targets_from_rows=resolve_targets,
            )
        ),
    )
    monkeypatch.setattr(module, "batch_check_verified_business_visible", check_visible)
    monkeypatch.setattr(module.SpaceFileDao, "async_list_children", AsyncMock(return_value=children))
    monkeypatch.setattr(service, "_get_file_change_excluded_ids", AsyncMock(return_value=excluded_ids))
    monkeypatch.setattr(service, "_handle_file_folder_extra_info", enrich)

    response = await filelib.get_filelist(
        request=None,
        knowledge_id=137,
        parent_id=742,
        keyword=None,
        status=None,
        page_size=10,
        cursor=None,
        version_repo=None,
        doc_repo=None,
    )

    assert response.data["data"] == [{"id": file_id} for file_id in (745, 783) if file_id not in excluded_ids]
    assert response.data["writeable"] is True
    assert response.data["has_more"] is False
