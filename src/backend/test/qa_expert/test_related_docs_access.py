# ruff: noqa: RUF002
"""关联文档走 PermissionService.check(can_read, knowledge_space)，不扫 list_accessible_ids。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.qa_expert.domain import related_docs_access


async def test_missing_file_returns_none(monkeypatch):
    monkeypatch.setattr(related_docs_access, "_file_belongs_to_space", AsyncMock(return_value=False))
    space_read = AsyncMock(return_value=True)
    monkeypatch.setattr(related_docs_access, "_space_can_read", space_read)
    result = await related_docs_access.check_related_doc_access(
        SimpleNamespace(user_id=2, is_admin=lambda: False), 8, 15
    )
    assert result is None
    space_read.assert_not_awaited()


async def test_existing_file_without_space_read_returns_false(monkeypatch):
    monkeypatch.setattr(related_docs_access, "_file_belongs_to_space", AsyncMock(return_value=True))
    monkeypatch.setattr(related_docs_access, "_space_can_read", AsyncMock(return_value=False))
    result = await related_docs_access.check_related_doc_access(
        SimpleNamespace(user_id=2, is_admin=lambda: False), 8, 15
    )
    assert result is False


async def test_existing_file_with_space_read_returns_true(monkeypatch):
    monkeypatch.setattr(related_docs_access, "_file_belongs_to_space", AsyncMock(return_value=True))
    monkeypatch.setattr(related_docs_access, "_space_can_read", AsyncMock(return_value=True))
    result = await related_docs_access.check_related_doc_access(
        SimpleNamespace(user_id=9, is_admin=lambda: False), 8, 15
    )
    assert result is True


async def test_same_space_permission_is_cached(monkeypatch):
    monkeypatch.setattr(related_docs_access, "_file_belongs_to_space", AsyncMock(return_value=True))
    space_read = AsyncMock(return_value=True)
    monkeypatch.setattr(related_docs_access, "_space_can_read", space_read)
    cache: dict[int, bool] = {}
    user = SimpleNamespace(user_id=9, is_admin=lambda: False)
    first = await related_docs_access.check_related_doc_access(user, 8, 15, space_cache=cache)
    second = await related_docs_access.check_related_doc_access(user, 8, 16, space_cache=cache)
    assert first is True
    assert second is True
    space_read.assert_awaited_once()


async def test_space_can_read_uses_permission_check_not_list(monkeypatch):
    calls: list[dict] = []

    async def fake_check(*, user_id, relation, object_type, object_id, login_user=None):
        calls.append(
            {
                "user_id": user_id,
                "relation": relation,
                "object_type": object_type,
                "object_id": object_id,
                "login_user": login_user,
            }
        )
        return True

    monkeypatch.setattr(
        "bisheng.permission.domain.services.permission_service.PermissionService.check",
        fake_check,
    )
    user = SimpleNamespace(user_id=9, is_admin=lambda: False)
    assert await related_docs_access._space_can_read(user, 8) is True
    assert calls == [
        {
            "user_id": 9,
            "relation": "can_read",
            "object_type": "knowledge_space",
            "object_id": "8",
            "login_user": user,
        }
    ]
    assert not any("list_accessible" in str(item) for item in calls)


def test_related_doc_display_title_prefers_file_name():
    row = SimpleNamespace(file_name="炼钢规程.pdf", alias_name="规范名称.pdf")
    assert related_docs_access.related_doc_display_title(row) == "炼钢规程.pdf"
    assert (
        related_docs_access.related_doc_display_title(SimpleNamespace(file_name="", alias_name="规范名称.pdf"))
        == "规范名称.pdf"
    )
    assert related_docs_access.related_doc_display_title(None) is None


async def test_load_related_doc_title_returns_file_name(monkeypatch):
    monkeypatch.setattr(
        related_docs_access,
        "_load_related_doc_file",
        AsyncMock(return_value=SimpleNamespace(file_name="工艺说明.docx", alias_name=None)),
    )
    assert await related_docs_access.load_related_doc_title(8, 15) == "工艺说明.docx"


async def test_other_user_personal_space_allowed_for_admin(monkeypatch):
    """他人个人库：系统管理员仍走 can_read，与全局数据可见一致。"""
    monkeypatch.setattr(related_docs_access, "_file_belongs_to_space", AsyncMock(return_value=True))
    monkeypatch.setattr(related_docs_access, "_personal_space_owner_id", AsyncMock(return_value=100))
    space_read = AsyncMock(return_value=True)
    monkeypatch.setattr(related_docs_access, "_space_can_read", space_read)
    admin = SimpleNamespace(user_id=1, is_admin=lambda: True)
    assert await related_docs_access.check_related_doc_access(admin, 8, 15) is True
    space_read.assert_awaited_once()


async def test_other_user_personal_space_denied_for_non_admin(monkeypatch):
    """他人个人库：普通用户不调用 can_read，直接 forbidden。"""
    monkeypatch.setattr(related_docs_access, "_file_belongs_to_space", AsyncMock(return_value=True))
    monkeypatch.setattr(related_docs_access, "_personal_space_owner_id", AsyncMock(return_value=100))
    space_read = AsyncMock(return_value=True)
    monkeypatch.setattr(related_docs_access, "_space_can_read", space_read)
    stranger = SimpleNamespace(user_id=2, is_admin=lambda: False)
    assert await related_docs_access.check_related_doc_access(stranger, 8, 15) is False
    space_read.assert_not_awaited()


async def test_owner_personal_space_still_uses_space_read(monkeypatch):
    monkeypatch.setattr(related_docs_access, "_file_belongs_to_space", AsyncMock(return_value=True))
    monkeypatch.setattr(related_docs_access, "_personal_space_owner_id", AsyncMock(return_value=100))
    space_read = AsyncMock(return_value=True)
    monkeypatch.setattr(related_docs_access, "_space_can_read", space_read)
    owner = SimpleNamespace(user_id=100, is_admin=lambda: False)
    assert await related_docs_access.check_related_doc_access(owner, 8, 15) is True
    space_read.assert_awaited_once()


async def test_non_personal_space_admin_still_uses_space_read(monkeypatch):
    monkeypatch.setattr(related_docs_access, "_file_belongs_to_space", AsyncMock(return_value=True))
    monkeypatch.setattr(related_docs_access, "_personal_space_owner_id", AsyncMock(return_value=None))
    space_read = AsyncMock(return_value=True)
    monkeypatch.setattr(related_docs_access, "_space_can_read", space_read)
    admin = SimpleNamespace(user_id=1, is_admin=lambda: True)
    assert await related_docs_access.check_related_doc_access(admin, 8, 15) is True
    space_read.assert_awaited_once()


async def test_resolve_favorite_reference_to_source(monkeypatch):
    fav = SimpleNamespace(
        id=77,
        knowledge_id=5,
        file_source="favorite_reference",
        user_metadata={"favorite_reference": {"source_space_id": 90, "source_file_id": 12}},
    )
    src = SimpleNamespace(id=12, knowledge_id=90, file_source="upload", user_metadata={})

    async def load(space_id, file_id):
        if (space_id, file_id) == (5, 77):
            return fav
        if (space_id, file_id) == (90, 12):
            return src
        return None

    monkeypatch.setattr(related_docs_access, "_load_related_doc_file", load)
    assert await related_docs_access.resolve_related_doc_target(5, 77) == (90, 12)


async def test_resolve_plain_file_unchanged(monkeypatch):
    row = SimpleNamespace(id=15, knowledge_id=8, file_source="upload", user_metadata={})
    monkeypatch.setattr(related_docs_access, "_load_related_doc_file", AsyncMock(return_value=row))
    assert await related_docs_access.resolve_related_doc_target(8, 15) == (8, 15)


async def test_resolve_missing_file_keeps_original_pair(monkeypatch):
    monkeypatch.setattr(related_docs_access, "_load_related_doc_file", AsyncMock(return_value=None))
    assert await related_docs_access.resolve_related_doc_target(8, 404) == (8, 404)


async def test_resolve_dangling_favorite_is_none(monkeypatch):
    fav = SimpleNamespace(
        id=77,
        knowledge_id=5,
        file_source="favorite_reference",
        user_metadata={"favorite_reference": {"source_space_id": 90, "source_file_id": 12}},
    )

    async def load(space_id, file_id):
        if (space_id, file_id) == (5, 77):
            return fav
        return None

    monkeypatch.setattr(related_docs_access, "_load_related_doc_file", load)
    assert await related_docs_access.resolve_related_doc_target(5, 77) is None


async def test_canonicalize_rewrites_favorite_token(monkeypatch):
    async def resolve(space_id, file_id):
        if (space_id, file_id) == (5, 77):
            return (90, 12)
        return space_id, file_id

    monkeypatch.setattr(related_docs_access, "resolve_related_doc_target", resolve)
    assert await related_docs_access.canonicalize_related_docs("5-77") == "90-12"
