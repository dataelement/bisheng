"""Scoped business identity and leaf-only reparent CAS for this repair run."""

from contextlib import contextmanager
from contextvars import ContextVar

from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.department import Department, UserDepartment
from bisheng.department.domain.repositories.current_repair_repository import CurrentDepartmentRepairRepository
from bisheng.department.domain.repositories.projection_recovery_repository import department_snapshot


class IamOneoffDepartmentRepository(CurrentDepartmentRepairRepository):
    @property
    def _proof_reads(self):
        if not hasattr(self, "_reads_context"):
            self._reads_context = ContextVar(f"department_proof_{id(self)}", default=None)
        return self._reads_context.get()

    @_proof_reads.setter
    def _proof_reads(self, value):
        if not hasattr(self, "_reads_context"):
            self._reads_context = ContextVar(f"department_proof_{id(self)}", default=None)
        self._reads_context.set(value)

    @contextmanager
    def read_scope(self):
        """Memoize one proof only; never reuse rows across T1/T2 or FGA writes."""
        previous = getattr(self, "_proof_reads", None)
        self._proof_reads = {}
        try:
            yield
        finally:
            self._proof_reads = previous

    async def ancestors(self, department, *, session=None, lock=False):
        cache = getattr(self, "_proof_reads", None)
        key = (id(session), lock, department["id"], department["parent_id"], department["path"])
        if cache is not None and key in cache:
            return [dict(row) for row in cache[key]]
        rows = await super().ancestors(department, session=session, lock=lock)
        if cache is not None:
            cache[key] = rows
        return [dict(row) for row in rows]

    async def get_many(self, identities):
        identities = sorted(set(identities))
        result = {}
        async with self._session() as db:
            for start in range(0, len(identities), 500):
                rows = (
                    await db.exec(select(Department).where(Department.id.in_(identities[start : start + 500])))
                ).all()
                result.update((int(row.id), department_snapshot(row)) for row in rows)
        return result

    async def inactive_membership_departments(self):
        async with self._session() as db:
            rows = (
                await db.exec(
                    select(Department.id)
                    .where(
                        (Department.status != "active") | (Department.is_deleted == 1),
                        select(UserDepartment.id).where(UserDepartment.department_id == Department.id).exists(),
                    )
                    .limit(200001)
                )
            ).all()
            if len(rows) > 200000:
                raise ValueError("INACTIVE_MEMBERSHIP_DEPARTMENT_LIMIT")
            return set(rows)

    async def identity(self, identity, *, session=None, lock=False):
        async with self._session(session) as db:
            statement = select(Department).where(Department.id == identity)
            if lock:
                statement = statement.with_for_update(nowait=True).execution_options(populate_existing=True)
            row = (await db.exec(statement)).first()
            if row is None:
                raise ValueError("IAM_LOCAL_DEPARTMENT_MISSING")
            return {
                "id": int(row.id),
                "tenant_id": int(row.tenant_id),
                "source": row.source,
                "external_id": row.external_id,
            }

    async def parent_by_external(self, source, external_id, *, session=None, lock=False):
        async with self._session(session) as db:
            statement = (
                select(Department).where(Department.source == source, Department.external_id == external_id).limit(2)
            )
            if lock:
                statement = statement.with_for_update(nowait=True).execution_options(populate_existing=True)
            rows = list((await db.exec(statement)).all())
            if len(rows) != 1:
                raise ValueError("IAM_PARENT_NOT_UNIQUE_OR_NOT_VISIBLE")
            return department_snapshot(rows[0])

    async def require_no_space_binding(self, department, *, session=None):
        from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace

        with bypass_tenant_filter():
            async with self._session(session) as db:
                if (
                    await db.exec(
                        select(DepartmentKnowledgeSpace.id)
                        .where(
                            DepartmentKnowledgeSpace.department_id == department["id"],
                        )
                        .limit(1)
                    )
                ).first() is not None:
                    raise ValueError("IAM_DEPARTMENT_SPACE_BINDING_REQUIRES_OWNER")

    async def require_leaf(self, department, *, session=None):
        await self.require_no_space_binding(department, session=session)
        cache = getattr(self, "_proof_reads", None)
        key = ("leaf", id(session), department["id"], department["parent_id"], department["path"])
        if cache is not None and key in cache:
            return
        with bypass_tenant_filter():
            async with self._session(session) as db:
                # Include archived/cross-tenant children and malformed path descendants.
                for predicate in (
                    Department.parent_id == department["id"],
                    Department.path.contains(f"/{department['id']}/"),
                ):
                    row = (
                        await db.exec(
                            select(Department.id).where(Department.id != department["id"], predicate).limit(1)
                        )
                    ).first()
                    if row is not None:
                        raise ValueError("IAM_ONEOFF_REQUIRES_LEAF")
        if cache is not None:
            cache[key] = True

    async def reparent_gate(self, before, reparent, operation_id, session):
        await self.require_leaf(before, session=session)
        source, target = reparent["source"], reparent["target"]
        statement = (
            self._guard(before)
            .where(
                Department.source == source["source"],
                Department.external_id == source["external_id"],
            )
            .values(
                parent_id=target["parent_id"],
                path=target["path"],
                permission_projection_state="FAILED_CLOSED",
                permission_projection_operation_id=operation_id,
            )
        )
        if (await session.exec(statement)).rowcount != 1:
            raise ValueError("IAM_REPARENT_GATE_CONFLICT")
