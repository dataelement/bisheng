"""Optional operational IAM composition; does not modify any online consumer."""

from bisheng.api.services.current_department_repair_runtime import CurrentDepartmentRepairRuntime
from bisheng.department.domain.repositories.iam_oneoff_repository import IamOneoffDepartmentRepository
from bisheng.department.domain.services.current_projection_repair import CurrentDepartmentRepairService
from bisheng.department.domain.services.iam_oneoff_repair import IamOneoffDepartmentService
from bisheng.permission.domain.services.department_recovery_plan import RecoveryBlockedError
from scripts.iam_department_lookup import IamDepartmentNotFound


class IamDepartmentRepairRuntime(CurrentDepartmentRepairRuntime):
    def __init__(self, *args, iam_lookup, **kwargs):
        super().__init__(*args, **kwargs)
        self.departments = IamOneoffDepartmentRepository()
        self.business = CurrentDepartmentRepairService(self.departments)
        self.iam_business = IamOneoffDepartmentService(self.departments)
        self.iam_lookup = iam_lookup
        self.iam_targets = set()

    async def prove_business(self, department, *, session=None, lock=False):
        if department["id"] not in self.iam_targets:
            try:
                return await super().prove_business(department, session=session, lock=lock)
            except ValueError as exc:
                if str(exc) not in {"ANCESTOR_INACTIVE", "ANCESTOR_MISSING", "BUSINESS_PATH_INVALID"}:
                    raise
            self.iam_targets.add(department["id"])
        if self.iam_lookup is None:
            raise RecoveryBlockedError("IAM_CONFIG_REQUIRED_FOR_UNPROVEN_BUSINESS")
        source, item, parent = None, None, None
        try:
            source = await self.departments.identity(department["id"], session=session, lock=lock)
            if source["source"] != self.iam_lookup.local_source:
                raise ValueError("IAM_LOCAL_SOURCE_MISMATCH")
            await self.departments.require_leaf(department, session=session)
            cache_only = lock and getattr(self, "enforce_prefetched_iam", False)
            try:
                item = (
                    self.iam_lookup.cached_department(source["external_id"])
                    if cache_only
                    else await self.iam_lookup.department(source["external_id"])
                )
            except IamDepartmentNotFound as exc:
                archive = getattr(self, "prove_archive", None)
                if archive is None:
                    raise
                return await archive(department, source, exc.evidence, session=session, lock=lock)
            if item["enable"] != 1:
                raise ValueError("IAM_DEPARTMENT_NOT_ENABLED")
            parent = (
                self.iam_lookup.cached_department(item["parentid"])
                if cache_only
                else await self.iam_lookup.department(item["parentid"])
            )
            return await self.iam_business.prove(
                department,
                source,
                item,
                parent,
                self.iam_lookup.source_fingerprint,
                session=session,
                lock=lock,
                require_current=not getattr(self, "dependency_preview", False),
            )
        except (ValueError, RecoveryBlockedError) as exc:
            blocked = RecoveryBlockedError(str(exc))
            blocked.details = getattr(exc, "details", {}) | {
                "local_identity": source,
                "iam_department": item,
                "iam_parent": parent,
            }
            raise blocked from exc

    async def prepare_external_facts(self, payload):
        if payload["business"].get("iam"):
            self.iam_targets.add(payload["department_id"])
            department = await self.departments.get(payload["department_id"])
            if department is None:
                raise RecoveryBlockedError("IAM_LOCAL_DEPARTMENT_MISSING")
            await self.prove_business(department)
