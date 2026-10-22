"""LocalExecutor.insert_set_font_code must never break the code it decorates.

The hook fires on any occurrence of the word ``matplotlib`` and then looks for the
import line to append the CJK font setup after. It used to call ``max()`` on that
search unguarded, so code mentioning ``matplotlib`` without a matching line (a
comment, a string) raised ValueError and the whole run failed before executing.
"""

from __future__ import annotations

import ast

import pytest

from bisheng_langchain.gpts.tools.code_interpreter import local_executor
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LocalExecutor

FONT_LINE = 'matplotlib.rc("font", family="WenQuanYi Zen Hei")'


@pytest.fixture(autouse=True)
def _keep_font_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    # isolation off would delete the developer's real matplotlib font cache
    monkeypatch.setattr(local_executor, "isolation_mode", lambda: "uid")


@pytest.mark.parametrize(
    "code",
    [
        "# plot it later with matplotlib\nprint(1)",
        'print("matplotlib is not installed")',
    ],
)
def test_mention_without_import_is_left_alone(code: str) -> None:
    assert LocalExecutor.insert_set_font_code(code) == code


def test_comma_separated_import_gets_the_font() -> None:
    out = LocalExecutor.insert_set_font_code("import pandas, numpy, matplotlib\nprint(1)")
    assert out.splitlines()[1:3] == ["import matplotlib", FONT_LINE]


def test_font_goes_after_the_last_import() -> None:
    code = "import matplotlib\nimport matplotlib.pyplot as plt\nplt.plot([1])"
    assert LocalExecutor.insert_set_font_code(code).splitlines()[2:4] == ["import matplotlib", FONT_LINE]


def test_indented_import_keeps_the_code_valid() -> None:
    code = "try:\n    import matplotlib.pyplot as plt\nexcept ImportError:\n    plt = None"
    out = LocalExecutor.insert_set_font_code(code)
    ast.parse(out)
    assert f"    {FONT_LINE}" in out.splitlines()


def test_code_without_matplotlib_is_untouched() -> None:
    assert LocalExecutor.insert_set_font_code("print(1)") == "print(1)"
