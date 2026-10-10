"""F072: hiding the "new app" button is not a permission check.

``create_app`` in ``web_menu`` gated the button only; ``POST /workflow/create``
and ``POST /assistant`` accepted any logged-in user, which is the first hop of
the workflow code-node RCE chain. Both endpoints now depend on
``UserPayload.get_app_creator_user``.
"""

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from bisheng.user.domain.services.auth import LoginUser

_BACKEND_ROOT = Path(__file__).resolve().parents[2] / "bisheng"


def _user(is_admin: bool) -> MagicMock:
    user = MagicMock()
    user.user_id = 42
    user.is_admin.return_value = is_admin
    return user


@pytest.fixture
def menu_check(monkeypatch):
    check = AsyncMock()
    monkeypatch.setattr(LoginUser, "assert_effective_web_menu_contains", check)
    return check


async def test_super_admin_bypasses_menu_check(monkeypatch, menu_check):
    user = _user(is_admin=True)
    monkeypatch.setattr(LoginUser, "get_login_user", AsyncMock(return_value=user))

    assert await LoginUser.get_app_creator_user(MagicMock()) is user
    menu_check.assert_not_called()


async def test_user_with_create_app_menu_is_admitted(monkeypatch, menu_check):
    user = _user(is_admin=False)
    monkeypatch.setattr(LoginUser, "get_login_user", AsyncMock(return_value=user))

    assert await LoginUser.get_app_creator_user(MagicMock()) is user
    menu_check.assert_awaited_once_with(42, "create_app")


async def test_user_without_create_app_menu_is_rejected(monkeypatch, menu_check):
    user = _user(is_admin=False)
    monkeypatch.setattr(LoginUser, "get_login_user", AsyncMock(return_value=user))
    menu_check.side_effect = HTTPException(status_code=403)

    with pytest.raises(HTTPException) as exc:
        await LoginUser.get_app_creator_user(MagicMock())
    assert exc.value.status_code == 403


def _login_user_dependency(file: Path, func_name: str) -> str:
    for node in ast.walk(ast.parse(file.read_text())):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == func_name:
            for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True):
                if arg.arg == "login_user":
                    return ast.unparse(default)
    raise AssertionError(f"{func_name} login_user dependency not found in {file.name}")


@pytest.mark.parametrize(
    "file, func_name",
    [
        (_BACKEND_ROOT / "api" / "v1" / "workflow.py", "create_flow"),
        (_BACKEND_ROOT / "api" / "v1" / "assistant.py", "create_assistant"),
    ],
)
def test_create_endpoints_depend_on_app_creator_gate(file, func_name):
    assert _login_user_dependency(file, func_name) == "Depends(UserPayload.get_app_creator_user)"
