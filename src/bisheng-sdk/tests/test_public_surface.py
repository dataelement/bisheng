"""公开面守卫 —— 准入门槛做成一条会红的测试（AC-01 / 03 / 12 / 30 / 33）。

新增第四个能力模块必须先证明它同时满足「平台特有」∧「写错了会出安全事故」，
**并先改这里的集合再写代码**。把门槛写在备忘录里没人看，写成断言就绕不过去。
chat / appdb 被否决的理由见 PRD-1 DEV-07 两表，不在这里重抄。
"""

from __future__ import annotations

import ast
import pkgutil
from pathlib import Path

import pytest

import bisheng_sdk

PACKAGE_DIR = Path(bisheng_sdk.__file__).parent
SOURCES = sorted(PACKAGE_DIR.glob("*.py"))


def test_public_modules_are_exactly_auth_retrieve_storage_errors():
    public = {name for _finder, name, _pkg in pkgutil.iter_modules([str(PACKAGE_DIR)]) if not name.startswith("_")}
    assert public == {"auth", "retrieve", "storage", "errors"}


def test_dunder_all_is_the_three_capability_modules():
    assert bisheng_sdk.__all__ == ("auth", "retrieve", "storage")


@pytest.mark.parametrize("name", ["chat", "appdb", "llm", "db", "client", "models"])
def test_the_modules_that_must_not_exist(name: str):
    with pytest.raises(ModuleNotFoundError):
        __import__(f"bisheng_sdk.{name}")


def _code_strings(source: Path) -> set[str]:
    """源文件里**代码**用到的字符串字面量与符号名（docstring 与注释不算）。

    区分二者是必须的：指南性质的 docstring 会提到 `OpenAI 兼容客户端` 与
    `BISHENG_APP_TOKEN` 这些名字，而"提到"与"用上"是两回事——用文本 grep 判定
    会逼着实现把解释删掉，那正是下一个人需要的解释。
    """
    tree = ast.parse(source.read_text(encoding="utf-8"))
    docstrings = {ast.get_docstring(node) for node in ast.walk(tree) if isinstance(node, _DOCSTRING_OWNERS)}
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value not in docstrings:
                names.add(node.value)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", None) or ""
            names.add(module)
            names.update(alias.name for alias in node.names)
    return names


_DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


@pytest.mark.parametrize("needle", ["openai", "OpenAI", "create_engine", "sqlalchemy", "psycopg", "sqlite3"])
def test_no_model_or_database_convenience_wrapper(needle: str):
    """两条标准库接法刻意不进 SDK：顺手包一层就是把它们请进来了。"""
    for source in SOURCES:
        assert needle not in _code_strings(source), f"{source.name} 的代码里用到了 {needle}"


@pytest.mark.parametrize("name", ["as_user", "on_behalf_of", "impersonate", "verify_token"])
def test_no_identity_override_symbol_anywhere(name: str):
    for source in SOURCES:
        assert f"def {name}" not in source.read_text(encoding="utf-8")


def test_only_env_module_reads_os_environ():
    """凭据与句柄的读取集中在 `_env.py` 一处，别处不得自己伸手去拿。"""
    offenders = [
        source.name
        for source in SOURCES
        if source.name not in {"_env.py"} and "os.environ" in source.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_app_token_is_read_only_through_the_env_module():
    """应用运行期凭据只能经 `_env.app_token()` 取，且只用于证明「哪个应用」。

    F055 已落地的托管契约要求 retrieve 同时带应用凭据与访问者凭据，因此这个名字
    在 SDK 里是**允许出现的**——但只允许出现在两处：`_env.py` 的常量，和
    `retrieve.py` 里对它的调用。散落到别处就意味着某条路径在拿应用身份当访问者用。
    """
    offenders = [
        source.name for source in SOURCES if source.name != "_env.py" and "BISHENG_APP_TOKEN" in _code_strings(source)
    ]
    assert offenders == []


def test_storage_never_exposes_a_url_or_bucket():
    from bisheng_sdk import storage

    names = set(dir(storage))
    assert not {name for name in names if name.endswith(("url", "link", "presign", "share"))}
    assert {"clear", "delete_prefix", "delete_many", "bucket", "endpoint"}.isdisjoint(names)


def test_version_declared_once():
    assert bisheng_sdk.__version__ == "0.1.1"
    hits = [source.name for source in SOURCES if '__version__ = "' in source.read_text(encoding="utf-8")]
    assert hits == ["__init__.py"]


def test_only_dependency_is_httpx():
    text = (PACKAGE_DIR.parent / "pyproject.toml").read_text(encoding="utf-8")
    block = text.split("dependencies = [", 1)[1].split("]", 1)[0]
    entries = [line.strip().strip(",").strip('"') for line in block.splitlines() if line.strip().startswith('"')]
    assert entries == ["httpx>=0.27,<1.0"]
