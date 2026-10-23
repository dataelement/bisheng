"""F063 workbench_chat policy: defaults, upsert validation, commercial gate."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.sensitive_word.domain.schemas import (
    SensitiveWordBusinessType,
    SensitiveWordCheckResult,
    SensitiveWordHit,
    SensitiveWordPolicyPayload,
)
from bisheng.sensitive_word.domain.services.sensitive_word_policy_service import (
    DEFAULT_AUTO_REPLY,
    SensitiveWordPolicyService,
)

WORKBENCH_DEFAULT_REPLY = "当前对话内容违反相关规范，请修改后重新输入"


def _policy(
    *,
    enabled=True,
    words_types=None,
    custom_words="",
    auto_reply="命中敏感词",
    extra_config=None,
):
    return SimpleNamespace(
        tenant_id=1,
        business_type=SensitiveWordBusinessType.WORKBENCH_CHAT.value,
        scope_type="tenant",
        scope_id="1",
        enabled=enabled,
        words_types=words_types or ["custom"],
        custom_words=custom_words,
        auto_reply=auto_reply,
        extra_config=extra_config or {},
    )


def _login_user():
    user = SimpleNamespace(user_id=7, tenant_id=1)
    return user


def test_workbench_default_reply_is_not_knowledge_space_copy():
    resp = SensitiveWordPolicyService.default_response(1, SensitiveWordBusinessType.WORKBENCH_CHAT.value)
    assert resp.auto_reply == WORKBENCH_DEFAULT_REPLY
    assert "上传内容命中敏感词" not in resp.auto_reply


def test_knowledge_space_default_reply_unchanged():
    resp = SensitiveWordPolicyService.default_response(1, SensitiveWordBusinessType.KNOWLEDGE_SPACE_FILE_PARSE.value)
    assert resp.auto_reply == DEFAULT_AUTO_REPLY


async def test_upsert_enabled_rejects_empty_word_types(monkeypatch):
    monkeypatch.setattr(
        SensitiveWordPolicyService,
        "_current_tenant_id",
        staticmethod(lambda _user: 1),
    )
    upsert = AsyncMock()
    monkeypatch.setattr(
        "bisheng.sensitive_word.domain.services.sensitive_word_policy_service.SensitiveWordPolicyDao.aupsert_policy",
        upsert,
    )
    payload = SensitiveWordPolicyPayload(
        enabled=True,
        words_types=[],
        custom_words="foo",
        auto_reply=WORKBENCH_DEFAULT_REPLY,
    )
    with pytest.raises(ValueError, match="请至少选择一个敏感词表"):
        await SensitiveWordPolicyService.aupsert_policy(
            _login_user(), SensitiveWordBusinessType.WORKBENCH_CHAT, payload
        )
    upsert.assert_not_called()


async def test_upsert_enabled_rejects_blank_auto_reply(monkeypatch):
    monkeypatch.setattr(SensitiveWordPolicyService, "_current_tenant_id", staticmethod(lambda _user: 1))
    upsert = AsyncMock()
    monkeypatch.setattr(
        "bisheng.sensitive_word.domain.services.sensitive_word_policy_service.SensitiveWordPolicyDao.aupsert_policy",
        upsert,
    )
    payload = SensitiveWordPolicyPayload(
        enabled=True,
        words_types=["builtin"],
        auto_reply="   ",
    )
    with pytest.raises(ValueError, match="自动回复内容不能为空"):
        await SensitiveWordPolicyService.aupsert_policy(
            _login_user(), SensitiveWordBusinessType.WORKBENCH_CHAT, payload
        )
    upsert.assert_not_called()


async def test_upsert_enabled_rejects_auto_reply_over_500(monkeypatch):
    monkeypatch.setattr(SensitiveWordPolicyService, "_current_tenant_id", staticmethod(lambda _user: 1))
    upsert = AsyncMock()
    monkeypatch.setattr(
        "bisheng.sensitive_word.domain.services.sensitive_word_policy_service.SensitiveWordPolicyDao.aupsert_policy",
        upsert,
    )
    payload = SensitiveWordPolicyPayload(
        enabled=True,
        words_types=["custom"],
        custom_words="foo",
        auto_reply="字" * 501,
    )
    with pytest.raises(ValueError, match="自动回复内容不能超过500字"):
        await SensitiveWordPolicyService.aupsert_policy(
            _login_user(), SensitiveWordBusinessType.WORKBENCH_CHAT, payload
        )
    upsert.assert_not_called()


async def test_upsert_disabled_still_writes_words_and_reply(monkeypatch):
    monkeypatch.setattr(SensitiveWordPolicyService, "_current_tenant_id", staticmethod(lambda _user: 1))
    upsert = AsyncMock(
        return_value=_policy(
            enabled=False,
            custom_words="保留词",
            auto_reply="保留回复",
            words_types=["custom"],
        )
    )
    monkeypatch.setattr(
        "bisheng.sensitive_word.domain.services.sensitive_word_policy_service.SensitiveWordPolicyDao.aupsert_policy",
        upsert,
    )
    payload = SensitiveWordPolicyPayload(
        enabled=False,
        words_types=["custom"],
        custom_words="保留词",
        auto_reply="保留回复",
    )
    resp = await SensitiveWordPolicyService.aupsert_policy(
        _login_user(), SensitiveWordBusinessType.WORKBENCH_CHAT, payload
    )
    assert upsert.await_args.kwargs["enabled"] is False
    assert upsert.await_args.kwargs["custom_words"] == "保留词"
    assert upsert.await_args.kwargs["auto_reply"] == "保留回复"
    assert resp.custom_words == "保留词"
    assert resp.auto_reply == "保留回复"


def test_inactive_when_not_pro_even_if_policy_enabled(monkeypatch):
    monkeypatch.setattr(SensitiveWordPolicyService, "_is_bisheng_pro", classmethod(lambda cls: False))
    monkeypatch.setattr(SensitiveWordPolicyService, "is_effective", classmethod(lambda cls, *a, **k: True))
    assert SensitiveWordPolicyService.is_workbench_content_safety_active(1) is False


def test_active_only_when_pro_and_effective(monkeypatch):
    monkeypatch.setattr(SensitiveWordPolicyService, "_is_bisheng_pro", classmethod(lambda cls: True))
    monkeypatch.setattr(SensitiveWordPolicyService, "is_effective", classmethod(lambda cls, *a, **k: True))
    assert SensitiveWordPolicyService.is_workbench_content_safety_active(1) is True

    monkeypatch.setattr(SensitiveWordPolicyService, "is_effective", classmethod(lambda cls, *a, **k: False))
    assert SensitiveWordPolicyService.is_workbench_content_safety_active(1) is False


def test_evaluate_returns_none_when_inactive_or_no_hits(monkeypatch):
    monkeypatch.setattr(
        SensitiveWordPolicyService,
        "is_workbench_content_safety_active",
        classmethod(lambda cls, _tid: False),
    )
    assert SensitiveWordPolicyService.evaluate_workbench_user_text(1, "任意") is None

    monkeypatch.setattr(
        SensitiveWordPolicyService,
        "is_workbench_content_safety_active",
        classmethod(lambda cls, _tid: True),
    )
    monkeypatch.setattr(
        SensitiveWordPolicyService,
        "check_text",
        classmethod(lambda cls, *a, **k: SensitiveWordCheckResult(enabled=True, hits=[], auto_reply="x")),
    )
    assert SensitiveWordPolicyService.evaluate_workbench_user_text(1, "任意") is None


def test_evaluate_returns_result_on_hit(monkeypatch):
    hit = SensitiveWordCheckResult(
        enabled=True,
        hits=[SensitiveWordHit(word="禁", count=1)],
        auto_reply=WORKBENCH_DEFAULT_REPLY,
    )
    monkeypatch.setattr(
        SensitiveWordPolicyService,
        "is_workbench_content_safety_active",
        classmethod(lambda cls, _tid: True),
    )
    monkeypatch.setattr(SensitiveWordPolicyService, "check_text", classmethod(lambda cls, *a, **k: hit))
    result = SensitiveWordPolicyService.evaluate_workbench_user_text(1, "禁词")
    assert result is hit
    assert result.auto_reply == WORKBENCH_DEFAULT_REPLY


def test_check_text_workbench_uses_existing_ac_engine(monkeypatch):
    monkeypatch.setattr(
        "bisheng.sensitive_word.domain.models.sensitive_word_policy.SensitiveWordPolicyDao.get_policy",
        lambda **kwargs: _policy(words_types=["builtin", "custom"], custom_words="自定义词"),
    )
    monkeypatch.setattr(
        SensitiveWordPolicyService,
        "load_builtin_words",
        classmethod(lambda cls: ("内置词",)),
    )
    result = SensitiveWordPolicyService.check_text(
        tenant_id=1,
        business_type=SensitiveWordBusinessType.WORKBENCH_CHAT,
        text="内置词和自定义词都命中",
    )
    assert result.enabled is True
    assert {hit.word for hit in result.hits} == {"内置词", "自定义词"}


def test_ineffective_policy_is_not_a_hit(monkeypatch):
    monkeypatch.setattr(
        "bisheng.sensitive_word.domain.models.sensitive_word_policy.SensitiveWordPolicyDao.get_policy",
        lambda **kwargs: _policy(enabled=True, words_types=["custom"], custom_words=""),
    )
    result = SensitiveWordPolicyService.check_text(
        tenant_id=1,
        business_type=SensitiveWordBusinessType.WORKBENCH_CHAT,
        text="任意内容",
    )
    assert result.enabled is False
    assert result.hits == []
