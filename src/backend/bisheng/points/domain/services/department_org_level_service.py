"""组织四级标签：租户内唯一公司根，子树级联 dept/office/squad。"""

from __future__ import annotations

from sqlalchemy import update
from sqlmodel import select

from bisheng.common.errcode.department import DepartmentNotFoundError
from bisheng.common.errcode.points import (
    PointsCompanyAlreadyExistsError,
    PointsCompanyRootConflictError,
    PointsNotCompanyRootError,
)
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import Department, DepartmentDao
from bisheng.points.domain.constants.org_levels import (
    ORG_LEVEL_COMPANY,
    ORG_LEVELS,
    org_level_for_relative_depth,
    relative_depth,
)
from bisheng.points.domain.schemas.points_schema import (
    ClearCompanyRootResponse,
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

    @staticmethod
    def _assert_no_company_nesting(company: Department, existing_companies: list) -> None:
        """禁止嵌套：目标在其他公司子树内，或子树内已有其他公司根。"""
        company_path = str(company.path or "")
        company_id = int(company.id)
        for row in existing_companies:
            other_id = int(row.id)
            if other_id == company_id:
                continue
            other_path = str(row.path or "")
            if not other_path or not company_path:
                continue
            # 目标落在已有公司子树内
            if company_path.startswith(other_path):
                raise PointsCompanyRootConflictError()
            # 已有公司落在目标子树内
            if other_path.startswith(company_path):
                raise PointsCompanyRootConflictError()

    @staticmethod
    def _assert_unique_company_root(company: Department, existing_companies: list) -> None:
        """租户内最多一个公司根：存在其他 company 时拒绝（不自动替换）。"""
        company_id = int(company.id)
        for row in existing_companies:
            if int(row.id) == company_id:
                continue
            raise PointsCompanyAlreadyExistsError()

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
        """指定公司根并仅在该子树内级联打标；租户内唯一公司，禁止嵌套。

        同一公司根可重复调用以重算子树。只清空目标 path 子树标签后再写入。
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
            existing_list = list(existing)
            # 先嵌套（更具体），再唯一性（并列第二家公司）。
            self._assert_no_company_nesting(company, existing_list)
            self._assert_unique_company_root(company, existing_list)

            # 仅清空本公司子树标签后重算。
            await session.exec(
                update(Department)
                .where(
                    Department.path.like(f"{company.path}%"),
                    Department.status == "active",
                )
                .values(org_level=None)
            )

            subtree = (
                await session.exec(
                    select(Department).where(
                        Department.path.like(f"{company.path}%"),
                        Department.status == "active",
                    )
                )
            ).all()
            levels = dict.fromkeys(ORG_LEVELS, 0)
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

    async def clear_company_root(self, user, dept_key: str) -> ClearCompanyRootResponse:
        """取消公司根：仅清空该公司 path 子树的 org_level。"""
        require_platform_admin(user)
        company = await self._resolve_department(dept_key)
        if company.org_level != ORG_LEVEL_COMPANY:
            raise PointsNotCompanyRootError()
        if not company.path:
            raise DepartmentNotFoundError(msg="部门缺少 path，无法取消公司标签")

        async with get_async_db_session() as session:
            labeled = (
                await session.exec(
                    select(Department).where(
                        Department.path.like(f"{company.path}%"),
                        Department.org_level.is_not(None),
                        Department.status == "active",
                    )
                )
            ).all()
            cleared_count = len(labeled)
            await session.exec(
                update(Department)
                .where(
                    Department.path.like(f"{company.path}%"),
                    Department.status == "active",
                )
                .values(org_level=None)
            )
            await session.commit()

        return ClearCompanyRootResponse(cleared_count=cleared_count)
