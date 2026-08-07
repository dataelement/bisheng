"""组织四级标签：唯一公司根 + 级联 dept/office/squad。"""

from __future__ import annotations

from sqlalchemy import update
from sqlmodel import select

from bisheng.common.errcode.department import DepartmentNotFoundError
from bisheng.common.errcode.points import PointsCompanyRootConflictError
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import Department, DepartmentDao
from bisheng.points.domain.constants.org_levels import (
    ORG_LEVEL_COMPANY,
    ORG_LEVELS,
    org_level_for_relative_depth,
    relative_depth,
)
from bisheng.points.domain.schemas.points_schema import (
    DepartmentOrgLevelItem,
    SetCompanyRootResponse,
)
from bisheng.points.domain.services.points_auth import require_platform_admin


class DepartmentOrgLevelService:
    """维护 department.org_level；不改拓扑与用户挂载。"""

    @staticmethod
    async def _resolve_department(dept_key: str) -> Department:
        """支持内部数字 id 或业务 dept_id。"""
        key = (dept_key or "").strip()
        if not key:
            raise DepartmentNotFoundError()
        if key.isdigit():
            row = await DepartmentDao.aget_by_id(int(key))
            if row is not None:
                return row
        row = await DepartmentDao.aget_by_dept_id(key)
        if row is None:
            raise DepartmentNotFoundError()
        return row

    async def list_org_levels(self, user) -> list[DepartmentOrgLevelItem]:
        """列出当前租户活跃部门的 org_level（只读）。"""
        _ = user  # 登录即可读；租户过滤由 ORM 事件注入。
        rows = await DepartmentDao.aget_all_active()
        return [
            DepartmentOrgLevelItem(
                id=int(row.id),
                dept_id=row.dept_id,
                name=row.name,
                parent_id=row.parent_id,
                path=row.path,
                org_level=row.org_level,
            )
            for row in rows
        ]

    async def set_company_root(self, user, dept_key: str) -> SetCompanyRootResponse:
        """指定唯一公司根并级联打标；已有其他 company 则 18205。

        同一公司根可重复调用以重算子树。清空本租户全部 org_level 后再写子树，
        子树外节点保持 NULL。
        """
        require_platform_admin(user)
        company = await self._resolve_department(dept_key)
        if not company.path:
            raise DepartmentNotFoundError(msg="部门缺少 path，无法级联打标")

        async with get_async_db_session() as session:
            existing = (
                await session.exec(
                    select(Department).where(
                        Department.org_level == ORG_LEVEL_COMPANY,
                        Department.status == "active",
                    )
                )
            ).all()
            for row in existing:
                if int(row.id) != int(company.id):
                    raise PointsCompanyRootConflictError()

            # 清空本租户标签；tenant_id 由自动注入约束在当前上下文。
            await session.exec(update(Department).values(org_level=None))

            subtree = (
                await session.exec(
                    select(Department).where(
                        Department.path.like(f"{company.path}%"),
                        Department.status == "active",
                    )
                )
            ).all()
            levels = {level: 0 for level in ORG_LEVELS}
            labeled = 0
            for node in subtree:
                rel = relative_depth(company.path, node.path)
                if rel is None:
                    continue
                label = org_level_for_relative_depth(rel)
                node.org_level = label
                session.add(node)
                levels[label] = levels.get(label, 0) + 1
                labeled += 1
            await session.commit()

        return SetCompanyRootResponse(
            company_id=int(company.id),
            labeled_count=labeled,
            levels={
                "company": levels.get(ORG_LEVEL_COMPANY, 0),
                "dept": levels.get("dept", 0),
                "office": levels.get("office", 0),
                "squad": levels.get("squad", 0),
            },
        )
