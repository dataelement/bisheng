"""Regression tests for WorkstationConfig application-center text fields.

`applicationCenterWelcomeMessage` / `applicationCenterDescription` were added
with `default=""` but a `pattern` that required at least one char (`...]+$`).
Any tenant whose stored config left these empty or unset (i.e. the default)
made `GET /api/v1/workstation/config` raise a pydantic ValidationError -> HTTP
500 -> the client rendered its full-screen "system maintenance" overlay, so
`/workspace/c/new` looked broken.

The fix relaxes the pattern to allow the empty string (`...]*$`) while keeping
the character whitelist for non-empty input.
"""

import pytest
from pydantic import ValidationError

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


def test_out_of_whitelist_char_still_rejected():
    # The pattern is a character whitelist (injection guard); relaxing +->*
    # must NOT weaken it for non-empty input.
    with pytest.raises(ValidationError):
        WorkstationConfig(applicationCenterWelcomeMessage="hi🚀")
