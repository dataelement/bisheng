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
    """只接受完整有效的组合; 固定模式不与新增配置求并集。"""
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
