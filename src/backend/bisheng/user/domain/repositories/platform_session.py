"""Serialized state transitions. The owning user row is the login serialization guard."""

from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter, strict_tenant_filter
from bisheng.user.domain.models.platform_session import PlatformRefreshToken, PlatformSession, PlatformWebTicket


class PlatformSessionRepository:
    def __init__(self, db):
        self.db = db

    def get(self, sid, *, lock=False):
        with bypass_tenant_filter():
            query = select(PlatformSession).where(PlatformSession.session_id == sid)
            if lock:
                query = query.with_for_update().execution_options(populate_existing=True)
            return self.db.exec(query).first()

    def refresh(self, digest, *, lock=False):
        with bypass_tenant_filter():
            query = (
                select(PlatformRefreshToken)
                .where(PlatformRefreshToken.token_hash == digest)
                .execution_options(populate_existing=True)
            )
            return self.db.exec(query.with_for_update() if lock else query).first()

    def generation(self, sid, generation):
        with bypass_tenant_filter():
            return self.db.exec(
                select(PlatformRefreshToken)
                .where(PlatformRefreshToken.session_id == sid, PlatformRefreshToken.generation == generation)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).first()

    def active_refreshes(self, sid):
        with bypass_tenant_filter():
            return self.db.exec(
                select(PlatformRefreshToken)
                .where(PlatformRefreshToken.session_id == sid, PlatformRefreshToken.state == "ACTIVE")
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()

    def sessions(self, user_id):
        with bypass_tenant_filter():
            return self.db.exec(
                select(PlatformSession)
                .where(PlatformSession.user_id == user_id)
                .order_by(PlatformSession.session_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()

    @strict_tenant_filter()
    def desktop_sessions(self, user_id, *, cursor=None, limit=20):
        query = select(PlatformSession).where(
            PlatformSession.user_id == user_id,
            PlatformSession.client_id == "bisheng-desktop",
            PlatformSession.parent_session_id.is_(None),
        )
        if cursor:
            query = query.where(PlatformSession.session_id > cursor)
        return self.db.exec(query.order_by(PlatformSession.session_id).limit(limit + 1)).all()

    def identity(self, user_id, tenant_id, *, lock=False):
        from bisheng.database.models.tenant import Tenant, UserTenant
        from bisheng.user.domain.models.user import User

        with bypass_tenant_filter():
            q = select(User).where(User.user_id == user_id)
            user = self.db.exec((q.with_for_update() if lock else q).execution_options(populate_existing=True)).first()
            tenant_query = select(Tenant).where(Tenant.id == tenant_id)
            tenant = self.db.exec(
                (tenant_query.with_for_update(read=True) if lock else tenant_query).execution_options(
                    populate_existing=True
                )
            ).first()
            membership_query = select(UserTenant).where(
                UserTenant.user_id == user_id, UserTenant.is_active == 1, UserTenant.status == "active"
            )
            memberships = self.db.exec(
                (membership_query.with_for_update() if lock else membership_query).execution_options(
                    populate_existing=True
                )
            ).all()
            if (
                not user
                or user.delete
                or not tenant
                or tenant.status != "active"
                or len(memberships) != 1
                or memberships[0].tenant_id != tenant_id
            ):
                return None
            return {
                "id": user.user_id,
                "user_name": user.user_name,
                "token_version": user.token_version,
                "tenant_id": tenant_id,
                "tenant_name": tenant.tenant_name,
            }

    def ticket(self, digest):
        with bypass_tenant_filter():
            return self.db.exec(
                select(PlatformWebTicket)
                .where(PlatformWebTicket.token_hash == digest)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).first()

    def cleanup_tickets(self, now, *, limit):
        with bypass_tenant_filter():
            expired = self.db.exec(
                select(PlatformWebTicket)
                .where(PlatformWebTicket.expires_at <= now)
                .order_by(PlatformWebTicket.expires_at, PlatformWebTicket.token_hash)
                .limit(limit)
                .with_for_update()
            ).all()
            for row in expired:
                self.db.delete(row)

    def add(self, row):
        self.db.add(row)

    def flush(self):
        self.db.flush()
