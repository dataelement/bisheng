"""Real C3 SQL candidates and F048 typed decisions, never membership enumeration."""

from datetime import datetime

import pytest

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.knowledge.application.legacy_documents import LegacyDocumentsApplication
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories import knowledge_compatibility_repository as compatibility
from bisheng.permission.application.resource_authorization import PermissionDecisionApplication
from bisheng.permission.domain.models import ResourcePermissionMode
from test.knowledge_unification.test_legacy_document_permissions import real_targets as real_targets


@pytest.fixture
async def pages(real_targets, monkeypatch):
    # The native fixture patches the same repository session port.
    sessions = compatibility.get_async_db_session
    async with sessions() as session:
        await session.connection()
        # Async SQLAlchemy uses the native SQLite connection for table creation.
        await session.run_sync(lambda active: KnowledgeFile.__table__.create(active.connection(), checkfirst=True))
        row = await session.get(Knowledge, 13)
        row.create_time = row.update_time = datetime(2026, 1, 1)
        session.add(
            Knowledge(
                id=16,
                tenant_id=101,
                type=3,
                state=1,
                user_id=9,
                name="A hidden",
                model="11",
                create_time=datetime(2026, 1, 1),
                update_time=datetime(2026, 1, 1),
            )
        )
        session.add(
            ResourcePermissionMode(
                id=16,
                tenant_id=101,
                resource_type="knowledge_space",
                resource_id="16",
                mode="CUSTOM",
                version=1,
                projection_state="CURRENT",
            )
        )
        session.add(KnowledgeFile(id=81, tenant_id=101, knowledge_id=13, file_name="failed", status=3))
        await session.commit()

    async def visible(checks, consistency=None):
        real_targets.fga.calls.append(("batch", checks))
        return [row["object"].endswith(":13") for row in checks]

    real_targets.fga.batch_check = visible
    return real_targets


async def test_old_list_reads_space_not_normal_and_filters_before_dto_pagination(pages):
    app = LegacyDocumentsApplication()
    first = await app.alist(identity=pages.user, sort_by="name", page_size=1)
    assert [(row.id, row.type) for row in first.data] == [(13, 0)]
    assert first.data[0].has_abnormal_files is True
    assert first.has_more is False
    current = await app.alist(identity=pages.user, legacy_view=False)
    assert [(row.id, row.type) for row in current.data] == [(13, 3)]


async def test_legacy_list_enriches_creator_and_actual_actions_only_after_visibility(pages, monkeypatch):
    from types import SimpleNamespace
    from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
    from bisheng.user.domain.models.user import UserDao
    from unittest.mock import Mock

    names = Mock(return_value=[SimpleNamespace(user_id=7, user_name="actual creator")])
    monkeypatch.setattr(UserDao, "get_user_by_ids", names)
    result = await LegacyDocumentsApplication().alist(identity=pages.user, sort_by="name", page_size=1)
    assert len(result.data) == 1
    row = result.data[0]
    assert row.user_name == "actual creator"
    assert "edit" in row.actions and row.copiable is True
    names.assert_called_once_with([7])
    assert row.type == 0 and row.has_abnormal_files is True
    assert KnowledgeService.permission_service is not None


async def test_legacy_create_uses_actual_space_type_for_original_converter(pages, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from bisheng.knowledge.domain.models.knowledge import KnowledgeCreate
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import KnowledgeSpaceCreateResp
    from bisheng.user.domain.models.user import UserDao

    async with compatibility.get_async_db_session() as session:
        actual = await session.get(Knowledge, 13)
    service = SimpleNamespace(create_knowledge_space=AsyncMock(
        return_value=KnowledgeSpaceCreateResp.model_validate(actual)
    ))
    monkeypatch.setattr(UserDao, "get_user_by_ids", Mock(
        return_value=[SimpleNamespace(user_id=7, user_name="actual creator")]
    ))
    result = await LegacyDocumentsApplication(space_service=service).acreate(
        request=None, identity=pages.user, command=KnowledgeCreate(name="created")
    )
    assert result.type == 0 and result.user_name == "actual creator"
    assert "edit" in result.actions and result.copiable is True
    assert actual.type == 3
    checks = [item for kind, rows in pages.fga.calls if kind == "batch" for item in rows]
    assert checks and all(item["object"] == "knowledge_space:13" for item in checks)


async def test_candidate_continuation_is_stable_and_tenant_visible_exact(pages):
    async def allowed(checks, consistency=None):
        return [True for _ in checks]

    pages.fga.batch_check = allowed
    app = LegacyDocumentsApplication()
    first = await app.alist(identity=pages.user, sort_by="name", page_size=1)
    assert [row.id for row in first.data] == [16] and first.has_more
    second = await app.alist(identity=pages.user, sort_by="name", page_size=1, cursor=first.next_cursor)
    assert [row.id for row in second.data] == [13] and not second.has_more
    assert {row.id for row in first.data + second.data} == {13, 16}
    abnormal = await app.alist(identity=pages.user, has_abnormal=True)
    assert [row.id for row in abnormal.data] == [13]


async def test_original_preferred_ids_input_is_not_limited_by_candidate_batch_size(pages):
    pages.fga.batch_check = _all_allowed
    app = LegacyDocumentsApplication()
    preferred = [*range(1000, 1250), 13]
    first = await app.alist(identity=pages.user, page_size=1, preferred_ids=preferred)
    assert [row.id for row in first.data] == [13] and first.has_more
    second = await app.alist(identity=pages.user, page_size=1, preferred_ids=preferred, cursor=first.next_cursor)
    assert [row.id for row in second.data] == [16] and not second.has_more


async def _all_allowed(checks, consistency=None):
    return [True for _ in checks]


async def test_public_knowledge_alias_is_normalized_before_original_strict_registry(pages):
    from bisheng.permission.application import business_authorization as auth

    owner = LegacyDocumentsApplication()
    registry = await auth.get_f048_resource_registry()
    runtime = await auth.get_f048_runtime()
    api = PermissionDecisionApplication(resources=registry, permission=runtime)
    actual = await owner.anormalize_permission_resource("knowledge_library", "13")
    assert actual == "knowledge_space"
    assert await api.check(resource_type=actual, resource_id="13", action="visible", actor=pages.actor)
    assert await owner.anormalize_permission_resource("knowledge_library", "12") == "knowledge_library"
    with pytest.raises(PermissionInvalidResourceError):
        await owner.anormalize_permission_resource("knowledge_library", "15")
    with pytest.raises(PermissionInvalidResourceError):
        await owner.anormalize_permission_resource("knowledge_library", "14")


async def test_real_public_check_boundary_resolves_old_namespace_before_typed_decision(pages, monkeypatch):
    from unittest.mock import AsyncMock

    from bisheng.permission.api.endpoints import decision
    from bisheng.permission.application import business_authorization as auth

    monkeypatch.setattr(decision, "permission_actor", AsyncMock(return_value=pages.actor))
    registry = await auth.get_f048_resource_registry()
    runtime = await auth.get_f048_runtime()
    result = await decision.check_permission_action(
        {"resource_type": "knowledge_library", "resource_id": "13", "action": "visible"},
        login_user=pages.user,
        api=PermissionDecisionApplication(resources=registry, permission=runtime),
        resources=LegacyDocumentsApplication(),
    )
    assert result.data == {"allowed": True}


@pytest.mark.parametrize("sort_by", ["update_time", "create_time"])
async def test_real_time_keyset_and_preference_cursor_do_not_drop_unpreferred_rows(pages, sort_by):
    async def allowed(checks, consistency=None):
        return [True for _ in checks]

    pages.fga.batch_check = allowed
    app = LegacyDocumentsApplication()
    first = await app.alist(identity=pages.user, sort_by=sort_by, page_size=1, preferred_ids=[13])
    assert [row.id for row in first.data] == [13] and first.has_more
    second = await app.alist(
        identity=pages.user, sort_by=sort_by, page_size=1, preferred_ids=[13], cursor=first.next_cursor
    )
    assert [row.id for row in second.data] == [16] and not second.has_more


@pytest.mark.parametrize("keyword", ["description-match", "failed"])
async def test_original_description_and_file_name_filters_remain_real_sql_candidates(pages, keyword):
    async with compatibility.get_async_db_session() as session:
        row = await session.get(Knowledge, 13)
        row.description = "description-match"
        await session.commit()
    result = await LegacyDocumentsApplication().alist(identity=pages.user, name=keyword)
    assert [row.id for row in result.data] == [13]


@pytest.mark.parametrize("ident", ["14", "15", "999"])
async def test_public_legacy_alias_has_no_super_admin_missing_foreign_or_retired_fallback(pages, monkeypatch, ident):
    from unittest.mock import AsyncMock

    from bisheng.permission.api.endpoints import decision
    from bisheng.permission.domain.services.permission_action_service import PermissionActor

    actor = PermissionActor(user_id=7, tenant_id=101, super_admin=True)
    monkeypatch.setattr(decision, "permission_actor", AsyncMock(return_value=actor))
    result = await decision.check_permission_action(
        {"resource_type": "knowledge_library", "resource_id": ident, "action": "visible"},
        login_user=pages.user,
        api=None,
        resources=LegacyDocumentsApplication(),
    )
    assert result.status_code == 25022 and result.data is None


async def test_public_legacy_alias_does_not_drop_personal_scope_at_the_http_admin_shortcut(pages, monkeypatch):
    from unittest.mock import AsyncMock

    from bisheng.common.errcode.open_api import PersonalTokenDataScopeError
    from bisheng.permission.api.endpoints import decision
    from bisheng.permission.application import business_authorization as auth
    from bisheng.permission.domain.services import data_scope
    from bisheng.permission.domain.services.permission_action_service import PermissionActor
    from test.permission.test_data_scope_enforcement import FakeResolver

    monkeypatch.setattr(data_scope, "_resolver", FakeResolver({}))
    actor = PermissionActor(user_id=7, tenant_id=101, super_admin=True, data_scope=data_scope.DATA_SCOPE_PERSONAL)
    monkeypatch.setattr(decision, "permission_actor", AsyncMock(return_value=actor))
    registry = await auth.get_f048_resource_registry()
    runtime = await auth.get_f048_runtime()
    result = await decision.check_permission_action(
        {"resource_type": "knowledge_library", "resource_id": "13", "action": "visible"},
        login_user=pages.user,
        api=PermissionDecisionApplication(resources=registry, permission=runtime),
        resources=LegacyDocumentsApplication(),
    )
    assert result.status_code == PersonalTokenDataScopeError.Code
    assert pages.fga.calls == []
