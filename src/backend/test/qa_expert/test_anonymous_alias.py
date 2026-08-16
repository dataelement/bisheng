# ruff: noqa: RUF002
"""T014：匿名别名时间序、删内容不重排、管理员破匿名、转公开用预存 reveal。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bisheng.database.models.qa_expert import AnonymousAlias
from bisheng.qa_expert.domain.identity import (
    IdentityService,
    alias_label_for_ord,
    persist_anonymous_choice,
    should_reveal_name,
)


def _viewer(*, user_id: int = 9, admin: bool = False, role: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        user_name=f"u{user_id}",
        is_admin=lambda: admin,
        role=role,
        is_global_super=False,
    )


def _service() -> IdentityService:
    svc = IdentityService()
    svc.alias_repo = MagicMock()
    svc.alias_repo.get_by_question_user = AsyncMock(return_value=None)
    svc.alias_repo.next_alias_ord = AsyncMock(return_value=1)
    svc.alias_repo.create = AsyncMock(side_effect=lambda row: row)
    svc.alias_repo.list_by_question_ids = AsyncMock(return_value=[])
    return svc


async def test_alias_assigned_in_time_order_a_then_b():
    svc = _service()
    first = await svc.get_or_assign_alias(question_id=10, user_id=2, tenant_id=1)
    assert first.alias_ord == 1
    assert first.alias_label == "匿名同事A"

    svc.alias_repo.get_by_question_user = AsyncMock(return_value=None)
    svc.alias_repo.next_alias_ord = AsyncMock(return_value=2)
    second = await svc.get_or_assign_alias(question_id=10, user_id=3, tenant_id=1)
    assert second.alias_ord == 2
    assert second.alias_label == "匿名同事B"
    assert alias_label_for_ord(27).endswith("AA")


async def test_deleted_content_does_not_reuse_alias_ord():
    svc = _service()
    existing = AnonymousAlias(
        id=1,
        question_id=10,
        user_id=2,
        alias_ord=1,
        alias_label="匿名同事A",
        tenant_id=1,
    )
    svc.alias_repo.get_by_question_user = AsyncMock(return_value=existing)
    again = await svc.get_or_assign_alias(question_id=10, user_id=2)
    assert again.alias_ord == 1
    assert again.alias_label == "匿名同事A"
    svc.alias_repo.next_alias_ord.assert_not_awaited()
    svc.alias_repo.create.assert_not_awaited()

    svc.alias_repo.get_by_question_user = AsyncMock(return_value=None)
    svc.alias_repo.next_alias_ord = AsyncMock(return_value=3)
    later = await svc.get_or_assign_alias(question_id=10, user_id=8)
    assert later.alias_ord == 3
    assert later.alias_label == "匿名同事C"


async def test_non_admin_response_has_no_real_name_fields():
    svc = _service()
    svc.alias_repo.get_by_question_user = AsyncMock(return_value=None)
    svc.alias_repo.next_alias_ord = AsyncMock(return_value=1)
    view = await svc.mask_identity(
        _viewer(admin=False),
        question_id=10,
        user_id=2,
        real_name="张三",
        anonymous=True,
        question_type="directed",
        reveal_on_public=0,
    )
    payload = view.to_dict(can_view_real_identity=False)
    assert payload["display_name"] == "匿名同事A"
    assert payload["anonymous"] is True
    assert "real_name" not in payload
    assert "real_user_id" not in payload
    assert view.real_name is None
    assert view.real_user_id is None


async def test_expert_library_admin_can_read_real_name():
    svc = _service()
    svc.alias_repo.get_by_question_user = AsyncMock(
        return_value=AnonymousAlias(
            question_id=10,
            user_id=2,
            alias_ord=1,
            alias_label="匿名同事A",
            tenant_id=1,
        )
    )
    view = await svc.mask_identity(
        _viewer(admin=False, role="管理员"),
        question_id=10,
        user_id=2,
        real_name="张三",
        anonymous=True,
        question_type="directed",
        reveal_on_public=0,
    )
    payload = view.to_dict(can_view_real_identity=True)
    assert payload["display_name"] == "匿名同事A"
    assert payload["real_name"] == "张三"
    assert payload["real_user_id"] == 2


def test_publish_uses_stored_reveal_without_asking_again():
    assert should_reveal_name(anonymous=True, question_type="public", reveal_on_public=1) is True
    assert should_reveal_name(anonymous=True, question_type="public", reveal_on_public=0) is False
    assert should_reveal_name(anonymous=True, question_type="directed", reveal_on_public=1) is False
    assert should_reveal_name(anonymous=False, question_type="public", reveal_on_public=0) is True


async def test_after_publish_revealed_name_uses_preset():
    svc = _service()
    view = await svc.mask_identity(
        _viewer(),
        question_id=10,
        user_id=2,
        real_name="张三",
        anonymous=True,
        question_type="public",
        reveal_on_public=1,
    )
    assert view.display_name == "张三"
    assert view.anonymous is False
    svc.alias_repo.create.assert_not_awaited()


def test_persist_anonymous_choice_requires_reveal_when_directed():
    import pytest

    from bisheng.common.errcode.qa_expert import QaExpertAnonymousRevealRequiredError

    assert persist_anonymous_choice(anonymous=False, reveal_on_public=True, question_type="directed") == (0, None)
    assert persist_anonymous_choice(anonymous=True, reveal_on_public=None, question_type="public") == (1, None)
    assert persist_anonymous_choice(anonymous=True, reveal_on_public=False, question_type="directed") == (1, 0)
    with pytest.raises(QaExpertAnonymousRevealRequiredError):
        persist_anonymous_choice(anonymous=True, reveal_on_public=None, question_type="directed")


async def test_preload_reuses_aliases_without_per_user_lookup():
    """列表预加载后，同页 mask 不得再按人 get_by_question_user。"""
    existing = AnonymousAlias(
        id=1,
        question_id=10,
        user_id=2,
        alias_ord=1,
        alias_label="匿名同事A",
        tenant_id=1,
    )
    svc = _service()
    svc.alias_repo.list_by_question_ids = AsyncMock(return_value=[existing])
    await svc.preload_for_questions([10])
    again = await svc.get_or_assign_alias(question_id=10, user_id=2)
    assert again.alias_label == "匿名同事A"
    svc.alias_repo.get_by_question_user.assert_not_awaited()
    svc.alias_repo.next_alias_ord.assert_not_awaited()
    svc.alias_repo.create.assert_not_awaited()
    svc.alias_repo.list_by_question_ids.assert_awaited_once()
