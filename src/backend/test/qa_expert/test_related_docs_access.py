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
