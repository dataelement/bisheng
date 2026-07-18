"""T007 — New F027 *InvalidCursorError* error codes (AC-08)."""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeInvalidCursorError
from bisheng.common.errcode.flow import AppInvalidCursorError
from bisheng.common.errcode.knowledge_space import KnowledgeSpaceInvalidCursorError


_CURSOR_ERROR_CLASSES = [
    (KnowledgeInvalidCursorError, 10991),
    (AppInvalidCursorError, 10550),
    (KnowledgeSpaceInvalidCursorError, 18070),
]


@pytest.mark.parametrize("error_cls,expected_code", _CURSOR_ERROR_CLASSES)
def test_error_inherits_base(error_cls, expected_code):
    assert issubclass(error_cls, BaseErrorCode)
    assert error_cls.Code == expected_code


@pytest.mark.parametrize("error_cls,_", _CURSOR_ERROR_CLASSES)
def test_error_msg_is_set(error_cls, _):
    assert isinstance(error_cls.Msg, str)
    assert error_cls.Msg.strip() != ""


def test_codes_unique_within_each_module_file():
    """Make sure the new code does not clash with an existing one in the same file."""
    errcode_dir = Path(__file__).resolve().parents[2] / "bisheng" / "common" / "errcode"
    pattern = re.compile(r"Code(?:\s*:\s*int)?\s*=\s*(\d+)")

    for module_name in ("knowledge", "flow", "knowledge_space"):
        text = (errcode_dir / f"{module_name}.py").read_text()
        codes = [int(m.group(1)) for m in pattern.finditer(text)]
        assert len(codes) == len(set(codes)), (
            f"duplicate codes in {module_name}.py: {sorted(codes)}"
        )


def test_new_codes_unique_across_modules():
    new_codes = {cls.Code for cls, _ in _CURSOR_ERROR_CLASSES}
    assert len(new_codes) == 3, "cursor error codes must be unique across modules"
