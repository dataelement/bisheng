from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import insert

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import SpaceFolderNotFoundError, SpacePermissionDeniedError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database.tenant_filter import register_tenant_filter_events
from bisheng.core.openfga.exceptions import FGAClientError
from bisheng.developer_token.domain.schemas import DeveloperTokenFileSyncRule
from bisheng.developer_token.domain.services.developer_token_service import DeveloperTokenService
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_repository_impl import KnowledgeRepositoryImpl
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService as Fine
from bisheng.permission.domain.services.permission_cache import PermissionCache
from bisheng.permission.domain.services.permission_service import PermissionService

SERVICE = "bisheng.knowledge.domain.services.knowledge_space_service"


@pytest.fixture
def target_state(monkeypatch):
    user = UserPayload(user_id=7, user_name="bound", user_role=[2], tenant_id=5)
    rows = [
        (SimpleNamespace(id=sid, name=name, type=3, state=state, user_id=99, tenant_id=5), level)
        for sid, name, level, state in [
            (117, "A read only", "public", 1),
            (118, "B equipment", "department", 1),
            (119, "C upload", "public", 1),
            (120, "D clinic", "team_ks", 1),
            (121, "E personal", "personal", 1),
            (122, "F unpublished", "public", 0),
        ]
    ]
    folders = [
        SimpleNamespace(id=fid, knowledge_id=118, file_name=str(fid), file_type=0, file_level_path=path)
        for fid, path in [(10, ""), (20, "/10"), (30, "/10/20"), (40, ""), (50, "/40")]
    ]
    bindings = []
    models = {name: {"id": name, "relation": name, "is_system": True} for name in ["editor", "viewer"]}
    models.update(
        {
            "allow": {
                "id": "allow",
                "relation": "viewer",
                "is_system": False,
                "permissions": ["upload_file_to_space", "upload_file_to_folder"],
                "permissions_explicit": True,
            },
            "deny": {
                "id": "deny",
                "relation": "editor",
                "is_system": False,
                "permissions": [],
                "permissions_explicit": True,
            },
        }
    )

    class KnowledgeRepo:
        async def find_file_sync_spaces(self, *, allowed_space_ids, keyword, after, limit):
            eligible = [
                row
                for row in rows
                if row[1] in {"public", "department"}
                and row[0].state == 1
                and (allowed_space_ids is None or row[0].id in allowed_space_ids)
                and (not keyword or keyword in row[0].name)
            ]

            def key(row):
                return (0 if row[1] == "public" else 1, row[0].name, row[0].id)

            return [row for row in sorted(eligible, key=key) if after is None or key(row) > after][:limit]

        async def find_file_sync_spaces_by_ids(self, ids):
            return [
                row for row in rows if row[0].id in ids and row[1] in {"public", "department"} and row[0].state == 1
            ]

        async def find_space_by_id(self, sid):
            return next((space for space, _ in rows if space.id == sid), None)

    class FileRepo:
        async def find_file_sync_folder_candidates(self, *, space_ids):
            return [folder for folder in folders if folder.knowledge_id in space_ids]

        async def find_file_sync_folders_by_ids(self, ids):
            return [folder for folder in folders if folder.id in ids]

        async def find_file_sync_space_ids_with_folders(self, *, space_ids, visible_folder_ids):
            return {
                folder.knowledge_id
                for folder in folders
                if folder.knowledge_id in space_ids and (visible_folder_ids is None or folder.id in visible_folder_ids)
            }

        async def list_file_sync_direct_children(self, *, knowledge_id, parent_path, visible_folder_ids, after, limit):
            return [
                folder
                for folder in folders
                if folder.knowledge_id == knowledge_id
                and folder.file_level_path == parent_path
                and (visible_folder_ids is None or folder.id in visible_folder_ids)
                and (after is None or (folder.file_name, folder.id) > after)
            ][:limit]

        async def find_file_sync_parent_paths_with_children(self, *, knowledge_id, parent_paths, visible_folder_ids):
            return {
                folder.file_level_path
                for folder in folders
                if folder.knowledge_id == knowledge_id
                and folder.file_level_path in parent_paths
                and (visible_folder_ids is None or folder.id in visible_folder_ids)
            }

    @asynccontextmanager
    async def session():
        yield object()

    async def tuples(*, object):
        return [
            {"user": "user:7", "relation": binding["relation"], "object": object}
            for binding in bindings
            if object == f"{binding['resource_type']}:{binding['resource_id']}"
        ]

    # 复现生产模型: 支持通用关系, 业务上传标识不是 OpenFGA 关系。
    fga = SimpleNamespace(
        read_tuples=AsyncMock(side_effect=tuples),
        list_objects=AsyncMock(side_effect=FGAClientError("relation_not_found")),
        check=AsyncMock(side_effect=FGAClientError("relation_not_found")),
    )
    monkeypatch.setattr(f"{SERVICE}.get_async_db_session", session)
    monkeypatch.setattr(f"{SERVICE}.KnowledgeRepositoryImpl", lambda _session: KnowledgeRepo())
    monkeypatch.setattr(f"{SERVICE}.KnowledgeFileRepositoryImpl", lambda _session: FileRepo())
    monkeypatch.setattr(PermissionService, "_get_fga", lambda: fga)
    monkeypatch.setattr(PermissionService, "_aget_fga", AsyncMock(return_value=fga))
    monkeypatch.setattr(PermissionService, "_evaluate_tenant_gate", AsyncMock(return_value=(False, None)))
    monkeypatch.setattr(PermissionService, "get_implicit_permission_level", AsyncMock(return_value=None))
    monkeypatch.setattr(PermissionService, "get_permission_level", AsyncMock(return_value=None))
    for name in ["get_check", "set_check", "get_list_objects", "set_list_objects"]:
        monkeypatch.setattr(PermissionCache, name, AsyncMock(return_value=None))
    monkeypatch.setattr(Fine, "get_relation_models_map", AsyncMock(return_value=models))
    monkeypatch.setattr(Fine, "get_current_user_subject_strings", AsyncMock(return_value={"user:7"}))
    monkeypatch.setattr(Fine, "get_binding_department_paths", AsyncMock(return_value={}))
    monkeypatch.setattr(Fine, "_public_knowledge_space_viewer_permission_ids", AsyncMock(return_value=set()))
    monkeypatch.setattr(
        "bisheng.permission.domain.services.fine_grained_permission_service._get_bindings",
        AsyncMock(return_value=bindings),
    )

    def grant(kind, sid, model):
        bindings.append(
            {
                "resource_type": kind,
                "resource_id": str(sid),
                "subject_type": "user",
                "subject_id": 7,
                "relation": models[model]["relation"],
                "model_id": model,
            }
        )

    return SimpleNamespace(user=user, grant=grant, fga=fga, rows=rows, folders=folders, bindings=bindings)


@pytest.mark.parametrize("model", ["editor", "allow"])
async def test_uploadable_space_is_listed_with_existing_fga_model(target_state, model):
    state = target_state
    state.grant("knowledge_space", 118, model)
    state.grant("knowledge_space", 117, "deny")
    state.grant("knowledge_space", 120, "editor")
    state.grant("knowledge_space", 122, "editor")
    page = await KnowledgeSpaceService.list_file_sync_target_spaces(
        login_user=state.user,
        cursor=None,
        page_size=1,
        keyword=None,
    )
    assert [(item.id, item.selectable) for item in page.items] == [(118, True)]
    assert not page.has_more
    assert not state.fga.list_objects.await_count


async def test_upload_filter_precedes_cursor_pagination_and_search(target_state):
    state = target_state
    for sid in [118, 119]:
        state.grant("knowledge_space", sid, "allow")
    state.grant("knowledge_space", 117, "deny")
    first = await KnowledgeSpaceService.list_file_sync_target_spaces(
        login_user=state.user,
        cursor=None,
        page_size=1,
        keyword=None,
    )
    second = await KnowledgeSpaceService.list_file_sync_target_spaces(
        login_user=state.user,
        cursor=first.next_cursor,
        page_size=1,
        keyword=None,
    )
    assert [item.id for item in first.items + second.items] == [119, 118]
    assert first.has_more and not second.has_more
    search = await KnowledgeSpaceService.list_file_sync_target_spaces(
        login_user=state.user,
        cursor=None,
        page_size=1,
        keyword="equipment",
    )
    assert [item.id for item in search.items] == [118]


async def test_deep_folder_grant_shows_only_navigation_ancestors(target_state):
    state = target_state
    state.grant("folder", 30, "allow")
    state.grant("folder", 40, "deny")
    page = await KnowledgeSpaceService.list_file_sync_target_spaces(
        login_user=state.user,
        cursor=None,
        page_size=20,
        keyword=None,
    )
    assert [(item.id, item.selectable, item.has_children) for item in page.items] == [(118, False, True)]
    root = await KnowledgeSpaceService.list_file_sync_target_folders(
        login_user=state.user,
        knowledge_id=118,
        parent_id=None,
        cursor=None,
        page_size=20,
    )
    assert [(item.id, item.selectable) for item in root.items] == [(10, False)]
    leaf = await KnowledgeSpaceService.list_file_sync_target_folders(
        login_user=state.user,
        knowledge_id=118,
        parent_id=20,
        cursor=None,
        page_size=20,
    )
    assert [(item.id, item.selectable) for item in leaf.items] == [(30, True)]


@pytest.mark.parametrize("folder_id,allowed", [(None, True), (30, True), (40, False), (50, False)])
async def test_final_target_uses_fine_upload_and_nearest_folder_binding(target_state, folder_id, allowed):
    state = target_state
    state.grant("knowledge_space", 118, "editor")
    state.grant("folder", 30, "allow")
    state.grant("folder", 40, "deny")
    call = KnowledgeSpaceService.validate_file_sync_target(
        login_user=state.user,
        knowledge_id=118,
        folder_id=folder_id,
    )
    if allowed:
        assert (await call).id == 118
    else:
        with pytest.raises(SpacePermissionDeniedError):
            await call
    assert not state.fga.check.await_count


async def test_no_upload_grant_hides_targets_and_rejects_save(target_state):
    state = target_state
    state.grant("knowledge_space", 118, "deny")
    page = await KnowledgeSpaceService.list_file_sync_target_spaces(
        login_user=state.user,
        cursor=None,
        page_size=20,
        keyword=None,
    )
    assert page.items == []
    with pytest.raises(SpacePermissionDeniedError):
        await KnowledgeSpaceService.validate_file_sync_target(
            login_user=state.user,
            knowledge_id=118,
            folder_id=None,
        )


async def test_wrong_space_folder_is_rejected_before_permission_check(target_state):
    with pytest.raises(SpaceFolderNotFoundError):
        await KnowledgeSpaceService.validate_file_sync_target(
            login_user=target_state.user,
            knowledge_id=119,
            folder_id=30,
        )
    target_state.fga.read_tuples.assert_not_awaited()


async def test_candidate_scan_does_not_truncate_before_uploadable_space(target_state):
    state = target_state
    state.rows.extend(
        [
            (SimpleNamespace(id=sid, name=str(sid), type=3, state=1, user_id=99, tenant_id=5), "public")
            for sid in range(1000, 1201)
        ]
    )
    state.grant("knowledge_space", 118, "allow")
    page = await KnowledgeSpaceService.list_file_sync_target_spaces(
        login_user=state.user,
        cursor=None,
        page_size=1,
        keyword=None,
    )
    assert [item.id for item in page.items] == [118]


async def test_save_rechecks_upload_permission_after_candidate_is_revoked(target_state):
    state = target_state
    state.grant("knowledge_space", 118, "allow")
    page = await KnowledgeSpaceService.list_file_sync_target_spaces(
        login_user=state.user,
        cursor=None,
        page_size=20,
        keyword=None,
    )
    assert [item.id for item in page.items] == [118]
    state.bindings.clear()
    with pytest.raises(SpacePermissionDeniedError):
        await KnowledgeSpaceService.validate_file_sync_target(
            login_user=state.user,
            knowledge_id=118,
            folder_id=None,
        )


async def test_fixed_directory_id_is_forwarded_to_final_upload_validation(monkeypatch):
    config = SimpleNamespace(
        portal=SimpleNamespace(
            document_types=[SimpleNamespace(code="POL", children=[SimpleNamespace(code="POL_EOUI")])],
            domains=[],
        )
    )
    monkeypatch.setattr(DeveloperTokenService, "_get_file_sync_portal_config", AsyncMock(return_value=config))
    validate = AsyncMock(return_value=SimpleNamespace(id=118))
    monkeypatch.setattr(DeveloperTokenService, "_validate_file_sync_target", validate)
    rule = DeveloperTokenFileSyncRule.model_validate(
        {
            "category": {"code": "POL", "subcategory_code": "POL_EOUI"},
            "business_domain": {"mode": "dynamic", "dynamic_source": "department_id"},
            "target_space": {"mode": "fixed", "knowledge_id": 118, "folder_id": 30},
            "dynamic_source": "department_id",
        }
    )
    await DeveloperTokenService._validate_file_sync_rule(5, 7, rule)
    assert validate.await_args.kwargs["folder_id"] == 30


async def test_real_candidate_queries_preserve_tenant_catalog_and_directory_scope(async_db_session):
    register_tenant_filter_events()
    session = async_db_session
    with bypass_tenant_filter():
        await session.execute(
            insert(Knowledge).values(
                [
                    {"id": sid, "name": str(sid), "type": 3, "state": status, "tenant_id": tenant}
                    for sid, status, tenant in [(118, 1, 5), (119, 1, 6), (120, 1, 5), (121, 0, 5)]
                ]
            )
        )
        await session.execute(
            insert(KnowledgeSpaceScope).values(
                [
                    {"space_id": sid, "level": level, "tenant_id": tenant, "owner_type": "department", "owner_id": 1}
                    for sid, level, tenant in [
                        (118, "department", 5),
                        (119, "public", 6),
                        (120, "team_ks", 5),
                        (121, "public", 5),
                    ]
                ]
            )
        )
        await session.execute(
            insert(KnowledgeFile).values(
                [
                    {"id": fid, "file_name": str(fid), "file_type": kind, "knowledge_id": sid, "tenant_id": tenant}
                    for fid, kind, sid, tenant in [(10, 0, 118, 5), (20, 1, 118, 5), (30, 0, 120, 5), (40, 0, 118, 6)]
                ]
            )
        )
    with DeveloperTokenService._target_tenant_context(5):
        rows = await KnowledgeRepositoryImpl(session).find_file_sync_spaces(
            allowed_space_ids=None,
            keyword=None,
            after=None,
            limit=200,
        )
        assert [space.id for space, _ in rows] == [118]
        folders = await KnowledgeFileRepositoryImpl(session).find_file_sync_folder_candidates(
            space_ids={space.id for space, _ in rows},
        )
        assert [folder.id for folder in folders] == [10]
