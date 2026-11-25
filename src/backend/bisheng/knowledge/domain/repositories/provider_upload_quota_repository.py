"""Durable two-subject byte reservations. All callers own the short transaction."""

from sqlalchemy import select, update

from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderQuota as Quota


class QuotaExceeded(ValueError):
    """No reservation was made for either subject."""


class ProviderUploadQuota:
    async def lock_tenant(self, db, tenant):
        # Even an empty quota ledger has a stable lock. SQLite has no row locks;
        # acquire its writer lock before any snapshot read in the test dialect.
        if db.get_bind().dialect.name == "sqlite":
            found = (await db.execute(update(Tenant).where(Tenant.id == tenant).values(id=tenant))).rowcount == 1
        else:
            found = await db.scalar(select(Tenant.id).where(Tenant.id == tenant).with_for_update()) == tenant
        if not found:
            raise ValueError("unknown quota tenant")

    @staticmethod
    def _subjects(key):
        return (("tenant", key.tenant_id), ("user", key.user_id))

    @staticmethod
    def _query(key, kind, subject):
        return select(Quota).where(
            Quota.tenant_id == key.tenant_id,
            Quota.subject_type == kind,
            Quota.subject_id == subject,
            Quota.accounting_kind == "original_bytes",
        )

    async def reserve(self, db, key, *, user_limit, tenant_limit, reopen=False):
        await self.lock_tenant(db, key.tenant_id)
        new = []
        for (kind, subject), limit in zip(self._subjects(key), (tenant_limit, user_limit), strict=True):
            if limit is not None and (type(limit) is not int or limit < 0):
                raise ValueError("invalid byte budget")
            query = self._query(key, kind, subject)
            prior = await db.scalar(
                query.where(Quota.space_id == key.space_id, Quota.version_id == key.version_id).with_for_update()
            )
            if reopen and prior is None:
                raise ValueError("released reservation missing")
            if prior is not None:
                if (
                    prior.operation_id != key.operation_id
                    or prior.byte_count != key.byte_count
                    or prior.state not in (("released",) if reopen else ("reserved", "charged"))
                ):
                    raise ValueError("version reservation conflict")
                if not reopen:
                    continue
            if limit is not None:
                # Current read, even when caller already holds a MySQL RR snapshot.
                counts = await db.scalars(
                    query.with_only_columns(Quota.byte_count)
                    .where(Quota.state.in_(("reserved", "charged")))
                    .with_for_update()
                )
                if sum(counts) + key.byte_count > limit:
                    raise QuotaExceeded(f"{kind} byte limit exceeded")
            if reopen:
                prior.state = "reserved"
                prior.revision += 1
                continue
            new.append(
                Quota(
                    tenant_id=key.tenant_id,
                    operation_id=key.operation_id,
                    space_id=key.space_id,
                    version_id=key.version_id,
                    subject_type=kind,
                    subject_id=subject,
                    accounting_kind="original_bytes",
                    byte_count=key.byte_count,
                )
            )
        if len(new) == 1:
            raise ValueError("incomplete reservation pair")
        db.add_all(new)
        await db.flush()

    async def _finish(self, db, key, state):
        await self.lock_tenant(db, key.tenant_id)
        rows = []
        for kind, subject in self._subjects(key):
            row = await db.scalar(
                self._query(key, kind, subject)
                .where(Quota.space_id == key.space_id, Quota.version_id == key.version_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                row is None
                or row.byte_count != key.byte_count
                or row.operation_id != key.operation_id
                or row.state not in ("reserved", state)
                or (row.state == "charged" and row.receipt_checksum != key.sha256)
            ):
                raise ValueError("reservation does not match upload")
            rows.append(row)
        for row in rows:
            if row.state != state:
                row.state = state
                row.revision += 1
                row.receipt_checksum = key.sha256 if state == "charged" else None
        await db.flush()

    async def verify(self, db, key):
        await self._finish(db, key, "charged")

    async def release(self, db, key):
        """Only after request-specific proof of non-reception; never on timeout."""
        await self._finish(db, key, "released")
