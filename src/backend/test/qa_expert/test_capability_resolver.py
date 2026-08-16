# ruff: noqa: RUF002
"""T004：CapabilityResolver 资格引擎单测（不查库）。"""

from types import SimpleNamespace

from bisheng.common.errcode.qa_expert import (
    QaExpertPublishDurationInvalidError,
    QaExpertQuestionAccessDeniedError,
)
from bisheng.qa_expert.domain.capability import (
    DISPLAY_PENDING_ADOPT,
    DISPLAY_SOLVED,
    DISPLAY_UNANSWERED,
    CapabilityResolver,
    CapabilitySnapshot,
    derive_display_status,
    is_expert_library_admin,
    is_unresolved,
)


def _user(*, user_id: int, admin: bool = False, role: str | None = None, user_name: str = "u") -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        user_name=user_name,
        role=role,
        is_admin=lambda: admin,
    )


def _question(
    *,
    user_id: int = 1,
    question_type: str = "public",
    content_locked: int = 0,
    adopt_count: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=10,
        user_id=user_id,
        question_type=question_type,
        content_locked=content_locked,
        adopt_count=adopt_count,
    )


def _expert(*, status: int = 1) -> SimpleNamespace:
    return SimpleNamespace(id=99, user_id=20, status=status)


def _resolve(user, question, **snapshot_kwargs):
    return CapabilityResolver().resolve(user, question, CapabilitySnapshot(**snapshot_kwargs))


def test_error_codes_module_183():
    assert QaExpertQuestionAccessDeniedError.Code == 18301
    assert QaExpertPublishDurationInvalidError.Code == 18310


def test_display_status_unanswered_pending_solved():
    assert derive_display_status(effective_answer_count=0, adopt_count=0) == DISPLAY_UNANSWERED
    assert derive_display_status(effective_answer_count=2, adopt_count=0) == DISPLAY_PENDING_ADOPT
    assert derive_display_status(effective_answer_count=2, adopt_count=1) == DISPLAY_SOLVED
    unanswered = _resolve(_user(user_id=1), _question(), effective_answer_count=0)
    pending = _resolve(_user(user_id=1), _question(), effective_answer_count=1)
    solved = _resolve(_user(user_id=1), _question(adopt_count=1), effective_answer_count=1)
    assert unanswered.display_status == DISPLAY_UNANSWERED
    assert pending.display_status == DISPLAY_PENDING_ADOPT
    assert solved.display_status == DISPLAY_SOLVED
    assert "已关闭" not in {unanswered.display_status, pending.display_status, solved.display_status}


def test_unresolved_filter_set():
    assert is_unresolved(DISPLAY_UNANSWERED)
    assert is_unresolved(DISPLAY_PENDING_ADOPT)
    assert not is_unresolved(DISPLAY_SOLVED)


def test_directed_hidden_from_stranger():
    question = _question(user_id=1, question_type="directed")
    result = _resolve(
        _user(user_id=99),
        question,
        invited_user_ids=frozenset({20}),
        expert=_expert(),
    )
    assert result.capabilities.visible is False
    assert result.capabilities.can_answer is False
    assert result.capabilities.can_comment is False
    assert result.capabilities.can_edit is False


def test_directed_visible_to_invited_and_admin():
    question = _question(user_id=1, question_type="directed")
    invited = _resolve(
        _user(user_id=20),
        question,
        invited_user_ids=frozenset({20}),
        expert=_expert(),
    )
    admin = _resolve(
        _user(user_id=8, admin=True),
        question,
        invited_user_ids=frozenset({20}),
    )
    role_admin = _resolve(
        _user(user_id=9, role="管理员"),
        question,
        invited_user_ids=frozenset({20}),
    )
    assert invited.capabilities.visible is True
    assert invited.capabilities.can_answer is True
    assert admin.capabilities.visible is True
    assert admin.capabilities.can_view_real_identity is True
    assert role_admin.capabilities.visible is True
    assert is_expert_library_admin(_user(user_id=9, role="管理员"))
    names_only = SimpleNamespace(
        user_id=9,
        user_name="gzx03",
        is_admin=lambda: False,
        role_names=["管理员"],
    )
    assert is_expert_library_admin(names_only)


def test_public_expert_can_answer_before_first_adopt():
    result = _resolve(
        _user(user_id=20),
        _question(user_id=1, question_type="public", adopt_count=0),
        expert=_expert(),
    )
    assert result.capabilities.visible is True
    assert result.capabilities.can_answer is True


def test_public_expert_cannot_answer_after_first_adopt_if_not_eligible():
    result = _resolve(
        _user(user_id=20),
        _question(user_id=1, question_type="public", adopt_count=1),
        expert=_expert(),
        eligibility_user_ids=frozenset({30}),
        effective_answer_count=1,
    )
    assert result.capabilities.can_answer is False
    eligible = _resolve(
        _user(user_id=20),
        _question(user_id=1, question_type="public", adopt_count=1),
        expert=_expert(),
        eligibility_user_ids=frozenset({20}),
        effective_answer_count=1,
    )
    assert eligible.capabilities.can_answer is True


def test_disabled_expert_cannot_answer():
    result = _resolve(
        _user(user_id=20),
        _question(user_id=1, question_type="public"),
        expert=_expert(status=0),
    )
    assert result.capabilities.can_answer is False


def test_asker_cannot_answer_and_lock_blocks_edit():
    asker = _user(user_id=1)
    unlocked = _resolve(asker, _question(user_id=1, content_locked=0), expert=_expert())
    locked = _resolve(asker, _question(user_id=1, content_locked=1), expert=_expert())
    assert unlocked.capabilities.can_answer is False
    assert unlocked.capabilities.can_edit is True
    assert locked.capabilities.can_edit is False
    assert locked.capabilities.can_delete_question is False


def test_directed_comment_requires_effective_answer_except_asker():
    question = _question(user_id=1, question_type="directed")
    invited = _resolve(
        _user(user_id=20),
        question,
        invited_user_ids=frozenset({20}),
        expert=_expert(),
        user_has_effective_answer=False,
    )
    invited_answered = _resolve(
        _user(user_id=20),
        question,
        invited_user_ids=frozenset({20}),
        expert=_expert(),
        user_has_effective_answer=True,
    )
    asker = _resolve(_user(user_id=1), question, invited_user_ids=frozenset({20}))
    assert invited.capabilities.can_comment is False
    assert invited_answered.capabilities.can_comment is True
    assert asker.capabilities.can_comment is True


def test_ended_publish_blocks_restart():
    question = _question(user_id=1, question_type="directed", adopt_count=1)
    allowed = _resolve(
        _user(user_id=1),
        question,
        user_has_effective_answer=False,
        effective_answer_count=1,
    )
    ended = _resolve(
        _user(user_id=1),
        question,
        user_has_effective_answer=False,
        effective_answer_count=1,
        latest_publish_status="ended",
    )
    pending = _resolve(
        _user(user_id=1),
        question,
        user_has_effective_answer=False,
        effective_answer_count=1,
        has_pending_publish=True,
    )
    rejected = _resolve(
        _user(user_id=1),
        question,
        user_has_effective_answer=False,
        effective_answer_count=1,
        latest_publish_status="rejected",
    )
    assert allowed.capabilities.can_start_publish is True
    assert ended.capabilities.can_start_publish is False
    assert pending.capabilities.can_start_publish is False
    assert rejected.capabilities.can_start_publish is True
