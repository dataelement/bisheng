"""按公司根相对深度给部门节点 / 子树打 org_level.

创建 / org_sync / SSO upsert / 移动后子树重算共用本模块, 不再各抄一套深度映射.
公司子树外 (含未设公司根) 写成 None, 与 set_company_root 只标公司子树对齐.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import select

from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import Department
from bisheng.points.domain.constants.org_levels import (
    ORG_LEVEL_COMPANY,
    ORG_LEVELS,
    org_level_for_path,
)


async def aget_active_company_root(session) -> Department | None:
    """当前租户活跃公司根; 租户过滤由 ORM 事件注入. 租户内至多一个."""
    result = await session.exec(
        select(Department).where(
            Department.org_level == ORG_LEVEL_COMPANY,
            Department.status == "active",
        )
    )
    return result.first()


def apply_org_level_to_nodes(nodes: list[Any], company_path: str | None) -> tuple[int, dict[str, int]]:
    """给已加载节点写入 org_level, 返回 (打标数, 各级计数)."""
    levels = dict.fromkeys(ORG_LEVELS, 0)
    labeled = 0
    for node in nodes:
        label = org_level_for_path(company_path, getattr(node, "path", None))
        node.org_level = label
        if label:
            levels[label] = levels.get(label, 0) + 1
            labeled += 1
    return labeled, levels


async def apply_org_level_to_node(session, node: Department) -> None:
    """path 已写完后给单节点打标; 无公司根或落在公司子树外则为 None."""
    company = await aget_active_company_root(session)
    company_path = company.path if company is not None else None
    node.org_level = org_level_for_path(company_path, getattr(node, "path", None))


async def resolve_org_level_for_path(node_path: str | None) -> str | None:
    """独立查当前公司根后计算标签, 供已脱离 session 的新建行使用."""
    async with get_async_db_session() as session:
        company = await aget_active_company_root(session)
        company_path = company.path if company is not None else None
    return org_level_for_path(company_path, node_path)


def _expire_department_paths(session) -> None:
    """path 已被 SQL 批量改写时丢掉 identity map 里的旧 path."""
    identity_map = getattr(session, "identity_map", None)
    if identity_map is None:
        sync_session = getattr(session, "sync_session", None)
        identity_map = getattr(sync_session, "identity_map", None) if sync_session else None
    if identity_map is None:
        return
    for obj in list(identity_map.values()):
        if isinstance(obj, Department):
            session.expire(obj, ["path"])


async def relabel_subtree(session, subtree_path: str) -> None:
    """按当前 path 重算子树标签; 不在公司子树内则清成 None."""
    if not subtree_path:
        return
    _expire_department_paths(session)
    company = await aget_active_company_root(session)
    company_path = company.path if company is not None else None
    result = await session.exec(
        select(Department).where(
            Department.path.like(f"{subtree_path}%"),
            Department.status == "active",
        )
    )
    nodes = list(result.all())
    apply_org_level_to_nodes(nodes, company_path)
    for node in nodes:
        session.add(node)


async def relabel_subtree_standalone(subtree_path: str) -> None:
    """自管 session 的子树重算 (org_sync / SSO upsert 在 path 提交后调用)."""
    if not subtree_path:
        return
    async with get_async_db_session() as session:
        await relabel_subtree(session, subtree_path)
        await session.commit()
