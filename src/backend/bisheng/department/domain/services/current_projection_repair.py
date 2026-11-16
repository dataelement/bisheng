"""Owner proof for current department repair, independent of an old MOVE target."""

from bisheng.department.domain.services.department_recovery_facts import DepartmentRecoveryService


class DepartmentRepairBusinessError(ValueError):
    def __init__(self, reason, details):
        super().__init__(reason)
        self.details = details


class CurrentDepartmentRepairService:
    def __init__(self, repository):
        self.repository = repository
        self.active = DepartmentRecoveryService(repository)

    async def prove(self, department, *, session=None, lock=False):
        if department is None:
            raise ValueError("DEPARTMENT_MISSING_OR_NOT_VISIBLE")
        if department["deleted"] not in (0, 1) or department["status"] not in {"active", "archived"}:
            raise DepartmentRepairBusinessError("LIFECYCLE_UNPROVEN", {"department": department})
        if department["status"] == "active" and department["deleted"]:
            raise DepartmentRepairBusinessError("LIFECYCLE_CONFLICT_ACTIVE_DELETED", {"department": department})
        if department["status"] != "active":
            raise DepartmentRepairBusinessError(
                "DEPARTMENT_INACTIVE_REQUIRES_BUSINESS_OWNER", {"department": department}
            )
        try:
            proof = await self.active.prove(department, department["parent_id"], session=session, lock=lock)
        except ValueError as exc:
            details = await self.repository.failure_context(department, session=session)
            raise DepartmentRepairBusinessError(str(exc), details) from exc
        proof["direct_members"] = await self.repository.members(department["id"], session=session, lock=lock)
        return proof
