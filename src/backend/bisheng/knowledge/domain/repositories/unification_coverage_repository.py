"""Persisted Coverage facts in the caller's native transaction, never ready guesses."""

from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    get_current_tenant_id,
    is_tenant_filter_bypassed,
    strict_tenant_filter,
)
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun as Run
from bisheng.resource_reference.application.contracts import TransactionIdentity


def blocked(reason):
    raise ReferenceCoverageNotReadyError(reason="production_coverage_" + reason)


class CoverageContext:
    def __init__(self, session):
        self.session, self.tenant = session, get_current_tenant_id()
        if not isinstance(session, (Session, AsyncSession)):
            blocked("native_session_required")
        try:
            self.transaction = TransactionIdentity.capture(session)
        except (TypeError, ValueError) as error:
            raise ReferenceCoverageNotReadyError(reason="production_coverage_native_transaction_required") from error
        self.check()

    def check(self):
        if (
            type(self.tenant) is not int
            or self.tenant <= 0
            or type(get_current_tenant_id()) is not int
            or get_current_tenant_id() != self.tenant
            or is_tenant_filter_bypassed()
        ):
            blocked("tenant_changed")
        try:
            self.transaction.assert_current(self.session)
        except (TypeError, ValueError) as error:
            raise ReferenceCoverageNotReadyError(reason="production_coverage_transaction_changed") from error

    @contextmanager
    def read(self):
        self.check()
        with self.session.no_autoflush, strict_tenant_filter(), bypass_tenant_filter():
            yield
        self.check()


class UnificationCoverageRepository:
    def _pages(self, *, tenant_id=None, tenants=False):
        table = Tenant.__table__ if tenants else Run.__table__
        after = 0 if tenants else ""
        while True:
            query = select(table.c.id) if tenants else select(*table.c)
            query = query.where(table.c.id > after)
            if tenant_id is not None and not tenants:
                query = query.where(table.c.tenant_id == tenant_id)
            page = yield query.order_by(table.c.id).limit(200)
            if len(page) < 200:
                return
            after = page[-1]["id"]

    def _drive(self, session, plan):
        context, output = CoverageContext(session), []
        query = next(plan)
        try:
            while True:
                with context.read():
                    rows = tuple(session.execute(query).mappings())
                output.extend(dict(row) for row in rows)
                query = plan.send(rows)
        except StopIteration:
            context.check()
            return tuple(output)

    async def _adrive(self, session, plan):
        context, output = CoverageContext(session), []
        query = next(plan)
        try:
            while True:
                with context.read():
                    rows = tuple((await session.execute(query)).mappings())
                output.extend(dict(row) for row in rows)
                query = plan.send(rows)
        except StopIteration:
            context.check()
            return tuple(output)

    def load_runs(self, session, *, tenant_id=None):
        if isinstance(session, AsyncSession):
            blocked("sync_session_required")
        return self._drive(session, self._pages(tenant_id=tenant_id))

    async def aload_runs(self, session, *, tenant_id=None):
        if not isinstance(session, AsyncSession):
            blocked("async_session_required")
        return await self._adrive(session, self._pages(tenant_id=tenant_id))

    def load_tenants(self, session):
        return tuple(row["id"] for row in self._drive(session, self._pages(tenants=True)))

    async def aload_tenants(self, session):
        return tuple(row["id"] for row in await self._adrive(session, self._pages(tenants=True)))

    async def aallocate_epoch(self, session):
        """Global Tenant anchor serializes actual MAX+1, including tenant creation."""
        from sqlalchemy import func

        context = CoverageContext(session)
        with context.read():
            anchor = (
                await session.execute(select(Tenant.id).where(Tenant.id == 1).with_for_update())
            ).scalar_one_or_none()
        if anchor != 1:
            blocked("global_anchor_missing")
        with context.read():
            maximum = (await session.execute(select(func.max(Run.coverage_epoch)))).scalar_one()
        if maximum is not None and (type(maximum) is not int or not 0 < maximum < 2**63 - 1):
            blocked("epoch_exhausted")
        return (maximum or 0) + 1

    async def awrite_certificate(self, session, *, row, certificate, source_coverage):
        from sqlalchemy import update

        context = CoverageContext(session)
        with context.read():
            result = await session.execute(
                update(Run.__table__)
                .where(
                    Run.id == row["id"],
                    Run.tenant_id == row["tenant_id"],
                    Run.run_id == row["run_id"],
                    Run.phase == row["phase"],
                    Run.coverage_epoch.is_(None),
                )
                .values(
                    phase="completed",
                    coverage_epoch=certificate["coverage_epoch"],
                    source_coverage=source_coverage,
                    verification_report={**row["verification_report"], "reference_coverage": certificate},
                )
            )
        if result.rowcount != 1:
            blocked("certificate_compare_failed")

    async def ainsert_empty_certificate(self, session, *, row):
        from sqlalchemy import insert

        context = CoverageContext(session)
        with context.read():
            await session.execute(insert(Run.__table__).values(**row))

    async def aflush_created_root(self, session, *, tenant):
        from sqlalchemy import inspect

        context = CoverageContext(session)
        if tenant not in session.new or not inspect(tenant).pending or tenant.id != 1:
            blocked("actual_new_root_required")
        await session.flush()
        context.check()
