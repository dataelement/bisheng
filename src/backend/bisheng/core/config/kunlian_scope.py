"""昆联配置范围的纯数据校验, 不从目录或请求推导登录授权。"""

from collections.abc import Collection, Mapping


def _identifier(value, limit):
    return (
        isinstance(value, str)
        and 0 < len(value) <= limit
        and all(
            not char.isspace() and char != "*" and ord(char) >= 32 and not 127 <= ord(char) <= 159 for char in value
        )
    )


def resolve_scope_pairs(
    mode: str, fixed_tenant: str, fixed_workspaces: Collection[str], tenant_workspaces: Mapping[str, Collection[str]]
) -> dict[str, frozenset[str]]:
    """校验范围配置; 目录模式无静态组合, 最终准入必须读取当前目录资格。"""
    if mode == "directory_active_tenants":
        return {}
    if mode == "fixed":
        pairs = {fixed_tenant: fixed_workspaces}
    elif mode == "tenant_workspace_map" and isinstance(tenant_workspaces, Mapping):
        pairs = tenant_workspaces
    else:
        raise ValueError("Invalid Kunlian scope mode")
    if not pairs:
        raise ValueError("Empty Kunlian scope policy")
    result = {}
    for tenant, workspaces in pairs.items():
        if (
            not _identifier(tenant, 64)
            or not isinstance(workspaces, (list, tuple, set, frozenset))
            or not workspaces
            or any(not _identifier(workspace, 128) for workspace in workspaces)
        ):
            raise ValueError("Invalid Kunlian tenant and workspace policy")
        result[tenant] = frozenset(workspaces)
    return result


def allows_scope_claims(mode, fixed_tenant, fixed_workspaces, tenant_workspaces, tenant, workspace) -> bool:
    """仅校验声明前置条件, 不代表有效目录成员或本地登录资格。"""
    if not _identifier(tenant, 64) or not _identifier(workspace, 128):
        return False
    try:
        pairs = resolve_scope_pairs(mode, fixed_tenant, fixed_workspaces, tenant_workspaces)
    except ValueError:
        return False
    return mode == "directory_active_tenants" or workspace in pairs.get(tenant, ())
