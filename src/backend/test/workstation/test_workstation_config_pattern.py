"""Regression tests for WorkstationConfig application-center text fields.

`applicationCenterWelcomeMessage` / `applicationCenterDescription` shipped with
`default=""` but a `pattern` requiring at least one char (`...]+$`). Any tenant
whose stored config left them empty or unset (the default) made
`GET /api/v1/workstation/config` raise a pydantic ValidationError -> HTTP 500,
so the client rendered its full-screen "system maintenance" overlay and
`/workspace/c/new` looked broken.

The pattern was a character whitelist that could not actually stop XSS (it
allowed `<>/"'&` ...) yet rejected the empty default plus emoji / non-CJK text.
Real XSS protection lives in the frontend (React escapes text nodes; none of
the render sites use dangerouslySetInnerHTML), so the whitelist was dead weight.
Aligned with feat/2.6.0 (commit 72fd1e8f0 "fix: unused pattern"): the pattern
is removed entirely, matching how these fields are validated on the main branch.
"""

from bisheng.api.v1.schemas import WorkstationConfig


def test_missing_fields_fall_back_to_empty_default():
    # Existing installs whose stored config predates these two fields:
    # WorkstationConfig(**raw) must not raise when they are absent.
    cfg = WorkstationConfig()
    assert cfg.applicationCenterWelcomeMessage == ""
    assert cfg.applicationCenterDescription == ""


def test_explicit_empty_strings_are_valid():
    # Admin cleared the text in 构建 -> 工作台; empty is a legal value.
    cfg = WorkstationConfig(
        applicationCenterWelcomeMessage="",
        applicationCenterDescription="",
    )
    assert cfg.applicationCenterWelcomeMessage == ""
    assert cfg.applicationCenterDescription == ""


def test_normal_cn_en_content_is_valid():
    cfg = WorkstationConfig(
        applicationCenterWelcomeMessage="欢迎使用应用中心 Welcome!",
        applicationCenterDescription="这里是描述, description.",
    )
    assert "欢迎" in cfg.applicationCenterWelcomeMessage
    assert "description" in cfg.applicationCenterDescription


def test_arbitrary_chars_accepted_after_pattern_removed():
    # The character whitelist has been removed (aligned with feat/2.6.0); input
    # the old pattern rejected (emoji, non-CJK scripts) must now pass. Only
    # max_length still constrains the field.
    text = "こんにちは 🚀 Привет"
    cfg = WorkstationConfig(applicationCenterWelcomeMessage=text)
    assert cfg.applicationCenterWelcomeMessage == text
