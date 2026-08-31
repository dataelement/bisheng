"""首钢门户运营岗「平台管理员」身份判定.

资格只认角色显示名精确匹配, 不得写入 is_admin() / get_admin_user().
"""

from __future__ import annotations

from typing import Any

PLATFORM_OPERATOR_ROLE_NAME = "平台管理员"


def has_platform_operator_role(user: Any) -> bool:
    """当前用户是否持有精确名为「平台管理员」的角色.

    只读 user.role_names; trim 后全等才算. 不把「管理员」等整页管理员名算进来.
    """
    if user is None:
        return False
    names = getattr(user, "role_names", None)
    if not names:
        return False
    if isinstance(names, str):
        candidates = [names]
    elif isinstance(names, (list, tuple, set, frozenset)):
        candidates = list(names)
    else:
        return False
    for raw in candidates:
        if str(raw).strip() == PLATFORM_OPERATOR_ROLE_NAME:
            return True
    return False


_PORTAL_ADMIN_ROLE_NAMES = frozenset({"管理员", "系统管理员", "admin"})

# 与 Platform userContext.adminMenuKeys 对齐, 另含 sys; 运营岗 WEB_MENU 必须丢掉这些.
PLATFORM_OPERATOR_ADMIN_MENU_KEYS = frozenset(
    {
        "admin",
        "backend",
        "board",
        "model",
        "log",
        "knowledge",
        "build",
        "evaluation",
        "system_config",
        "mark_task",
        "sys",
    }
)


def is_platform_operator_role_name(role_name: Any) -> bool:
    """角色显示名是否为保留名「平台管理员」(trim 后全等)."""
    return str(role_name or "").strip() == PLATFORM_OPERATOR_ROLE_NAME


def collect_user_info_role_names(login_user: Any) -> list[str]:
    """从登录态取出 role_names, 供 /user/info 回显. 缺省空列表."""
    names = getattr(login_user, "role_names", None) or []
    return [str(n) for n in names]


def strip_platform_operator_admin_menus(role_name: Any, menu_ids: list[str] | None) -> list[str]:
    """运营岗保存 WEB_MENU 时丢掉管理端 key, 只留工作台类; 其它角色原样去重.

    超管误勾 board/sys 也不能靠菜单进 Platform 管理端.
    """
    out: list[str] = []
    drop_admin = is_platform_operator_role_name(role_name)
    for menu_id in menu_ids or []:
        key = str(menu_id)
        if drop_admin and key in PLATFORM_OPERATOR_ADMIN_MENU_KEYS:
            continue
        if key not in out:
            out.append(key)
    return out


def resolve_user_info_role_label(role: Any, role_names: list[str] | None) -> Any:
    """/user/info 的 role 字段.

    优先级: AdminRole→admin; 门户整页名(管理员/系统管理员/admin)不降级;
    否则精确运营岗名; 否则保持入参. 不得把平台管理员并入整页白名单.
    """
    if role == "admin":
        return "admin"
    for name in role_names or []:
        text = str(name).strip()
        if text in _PORTAL_ADMIN_ROLE_NAMES or text.lower() == "admin":
            return text
    for name in role_names or []:
        text = str(name).strip()
        if text == PLATFORM_OPERATOR_ROLE_NAME:
            return PLATFORM_OPERATOR_ROLE_NAME
    return role


def can_platform_operate(user: Any) -> bool:
    """运营写资格: 超管或平台管理员.

    超管走 is_admin() / is_global_super; 运营岗只走角色名. 两者是并集, 不互相改写.
    """
    if user is None:
        return False
    if bool(getattr(user, "is_global_super", False)):
        return True
    check = getattr(user, "is_admin", None)
    if callable(check) and bool(check()):
        return True
    if not callable(check) and bool(check):
        return True
    return has_platform_operator_role(user)
