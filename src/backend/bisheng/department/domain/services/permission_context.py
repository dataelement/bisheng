"""Supply complete department membership facts without deciding resource access."""

from __future__ import annotations

import asyncio

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.department.domain.repositories.permission_context_repository import DepartmentPermissionContextRepository
from bisheng.permission.application.department_context import ActorDepartmentContext


class DepartmentPermissionContextProvider:
    def __init__(self, repository: DepartmentPermissionContextRepository | None = None) -> None:
        self._repository = repository or DepartmentPermissionContextRepository()

    async def load(self, user_id: int) -> ActorDepartmentContext:
        async with asyncio.timeout(5):
            direct, rows = await self._repository.load_ancestry(user_id, limit=100)
        result: set[int] = set()
        for department_id in direct:
            current = department_id
            visited: set[int] = set()
            while current is not None:
                if current in visited or current not in rows:
                    raise PermissionPublishNotReadyError(msg="Department ancestry is invalid")
                visited.add(current)
                row = rows[current]
                if row.status != "active" or row.projection_state != "CURRENT":
                    raise PermissionPublishNotReadyError(msg="Department permission facts are not current")
                result.add(current)
                current = row.parent_id
        return ActorDepartmentContext(user_id=user_id, subtree_department_ids=tuple(sorted(result)))
