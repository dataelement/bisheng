"""AT-03: 运营岗角色名精确匹配, 且不把人变成超管."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.user.domain.services.platform_operator import (
    PLATFORM_OPERATOR_ROLE_NAME,
    can_platform_operate,
    collect_user_info_role_names,
    has_platform_operator_role,
    resolve_user_info_role_label,
)


class _User:
    """可控 is_admin 的夹具; 运营岗不得把该标志改成 True."""

    def __init__(
        self,
        *,
        admin: bool = False,
        is_global_super: bool = False,
        role_names: list[str] | None = None,
    ) -> None:
        self._admin = admin
        self.is_global_super = is_global_super
        self.role_names = list(role_names or [])

    def is_admin(self) -> bool:
        return self._admin


def test_helper_constant_is_exact_display_name() -> None:
    assert PLATFORM_OPERATOR_ROLE_NAME == "平台管理员"


@pytest.mark.parametrize(
    ("role_names", "expected"),
    [
        (["平台管理员"], True),
        ([" 平台管理员 "], True),
        (["普通用户", "平台管理员"], True),
        ([], False),
        (["管理员"], False),
        (["系统管理员"], False),
        (["admin"], False),
        (["xx平台管理员"], False),
        (["平台管理员x"], False),
        (["平台 管理员"], False),
    ],
)
def test_helper_has_platform_operator_role_exact_match(
    role_names: list[str],
    expected: bool,
) -> None:
    user = _User(role_names=role_names)
    assert has_platform_operator_role(user) is expected
    assert user.is_admin() is False


def test_helper_has_platform_operator_role_rejects_none_and_missing() -> None:
    assert has_platform_operator_role(None) is False
    assert has_platform_operator_role(SimpleNamespace()) is False
    assert has_platform_operator_role(SimpleNamespace(role_names=None)) is False


def test_helper_can_platform_operate_super_admin_and_operator() -> None:
    assert can_platform_operate(_User(admin=True)) is True
    assert can_platform_operate(_User(is_global_super=True)) is True
    operator = _User(role_names=["平台管理员"])
    assert can_platform_operate(operator) is True
    assert operator.is_admin() is False


def test_helper_can_platform_operate_rejects_ordinary_and_portal_admin_names() -> None:
    assert can_platform_operate(None) is False
    assert can_platform_operate(_User()) is False
    assert can_platform_operate(_User(role_names=["管理员"])) is False
    assert can_platform_operate(_User(role_names=["系统管理员"])) is False
    assert can_platform_operate(_User(role_names=["admin"])) is False


def test_user_info_role_label_emits_operator_name() -> None:
    assert resolve_user_info_role_label([5], ["平台管理员"]) == "平台管理员"
    assert resolve_user_info_role_label([5], [" 平台管理员 "]) == "平台管理员"


def test_user_info_role_label_admin_and_portal_admin_unchanged() -> None:
    assert resolve_user_info_role_label("admin", ["平台管理员"]) == "admin"
    assert resolve_user_info_role_label([5], ["管理员"]) == "管理员"
    assert resolve_user_info_role_label([5], ["系统管理员"]) == "系统管理员"
    # 整页管理员 + 运营岗: 不降级成运营岗.
    assert resolve_user_info_role_label([5], ["管理员", "平台管理员"]) == "管理员"


def test_user_read_exposes_role_names() -> None:
    # UserRead 在 conftest 里被 premock, 不能实例化真 schema; 测下发 helper + 源码字段.
    operator = _User(role_names=["平台管理员"])
    assert collect_user_info_role_names(operator) == ["平台管理员"]
    from pathlib import Path

    model_src = (Path(__file__).resolve().parents[2] / "bisheng" / "user" / "domain" / "models" / "user.py").read_text(
        encoding="utf-8"
    )
    assert "role_names: list[str] | None = None" in model_src


@pytest.mark.asyncio
async def test_get_admin_user_rejects_platform_operator() -> None:
    from fastapi import HTTPException

    from bisheng.user.domain.services.auth import LoginUser

    operator = _User(role_names=["平台管理员"])
    assert operator.is_admin() is False
    denied = HTTPException(status_code=403, detail="No permission to operate")
    with patch.object(LoginUser, "get_login_user", new=AsyncMock(return_value=operator)):
        with patch(
            "bisheng.user.domain.services.auth.UnAuthorizedError.http_exception",
            return_value=denied,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await LoginUser.get_admin_user(auth_jwt=object())
    assert exc_info.value.status_code == 403
