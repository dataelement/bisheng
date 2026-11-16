"""Cross-process unique claim; unfinished claims reconcile through F048 ledger."""

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.workflow.application.kunlian_workflow_authorization import GrantReceipt, GrantReceiptResult
from bisheng.workflow.domain.models.kunlian_grant_receipt import KunlianGrantReceipt


class KunlianGrantReceiptRepository:
    @staticmethod
    def _receipt(row):
        result = GrantReceiptResult(row.status, row.applied_revision) if row.status is not None else None
        return GrantReceipt(row.digest, row.request_key, result)

    @staticmethod
    def _query(key):
        # Explicit tenant fence also works before runtime tenant-filter discovery.
        return select(KunlianGrantReceipt).where(
            KunlianGrantReceipt.tenant_id == get_current_tenant_id(), KunlianGrantReceipt.request_key == key
        )

    async def claim_or_read(self, key, digest):
        async with get_async_db_session() as session:
            row = (await session.exec(self._query(key))).first()
            if row is not None:
                return self._receipt(row), False
            row = KunlianGrantReceipt(tenant_id=get_current_tenant_id(), request_key=key, digest=digest)
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                row = (await session.exec(self._query(key))).first()
                if row is None:
                    raise
                return self._receipt(row), False
            return self._receipt(row), True

    async def complete(self, key, result):
        async with get_async_db_session() as session:
            row = (await session.exec(self._query(key).with_for_update())).first()
            if row is None:
                raise RuntimeError("Kunlian grant receipt missing")
            if row.status is not None:
                return GrantReceiptResult(row.status, row.applied_revision)
            row.status, row.applied_revision = result.status, result.applied_revision
            session.add(row)
            await session.commit()
        return result
