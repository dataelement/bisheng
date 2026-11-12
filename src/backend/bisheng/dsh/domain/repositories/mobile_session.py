"""Short SQL transactions for one phone's refresh-token rotation."""

from datetime import datetime
from uuid import uuid4

from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter, strict_tenant_filter
from bisheng.dsh.domain.models.mobile_session import DshMobileRefreshToken, DshMobileSession


class MobileSessionRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def snapshot(row):
        return {name: getattr(row, name) for name in type(row).model_fields}

    def locate_refresh(self, digest: str):
        # The credential digest is the only global lookup. Callers set the
        # returned tenant before any identity read or mutation.
        with bypass_tenant_filter():
            row = self.session.exec(
                select(
                    DshMobileSession.tenant_id,
                    DshMobileSession.user_id,
                    DshMobileSession.session_id,
                    DshMobileSession.expires_at,
                    DshMobileSession.token_version,
                    DshMobileSession.last_access_token_hash,
                )
                .join(DshMobileRefreshToken, DshMobileRefreshToken.session_id == DshMobileSession.session_id)
                .where(
                    DshMobileRefreshToken.token_hash == digest,
                    DshMobileRefreshToken.tenant_id == DshMobileSession.tenant_id,
                )
            ).first()
            names = (
                "tenant_id",
                "user_id",
                "session_id",
                "expires_at",
                "token_version",
                "last_access_token_hash",
            )
            return dict(zip(names, row, strict=True)) if row else None

    @strict_tenant_filter()
    def get(self, session_id: str, *, lock=False):
        statement = select(DshMobileSession).where(DshMobileSession.session_id == session_id)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return self.session.exec(statement).one_or_none()

    def create(
        self,
        *,
        tenant_id,
        user_id,
        token_version,
        expires_at,
        digest,
        access_hash,
        now,
    ):
        row = DshMobileSession(
            session_id=str(uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            token_version=token_version,
            state="ACTIVE",
            created_at=now,
            expires_at=expires_at,
            last_access_token_hash=access_hash,
        )
        self.session.add(row)
        self.session.add(
            DshMobileRefreshToken(
                token_hash=digest,
                tenant_id=tenant_id,
                session_id=row.session_id,
                generation=1,
                state="ACTIVE",
                created_at=now,
                expires_at=expires_at,
            )
        )
        self.session.flush()
        return self.snapshot(row)

    @strict_tenant_filter()
    def revoke(self, row):
        row.state = "REVOKED"
        self.session.add(row)
        for token in self.session.exec(
            select(DshMobileRefreshToken).where(DshMobileRefreshToken.session_id == row.session_id)
        ).all():
            token.state = "REVOKED"
            self.session.add(token)

    @strict_tenant_filter()
    def revoke_by_digest(self, digest: str):
        located = self.locate_refresh(digest)
        if located is None:
            return False
        row = self.get(located["session_id"], lock=True)
        if row is None:
            return False
        self.revoke(row)
        return True

    @strict_tenant_filter()
    def rotate(
        self,
        session_id: str,
        digest: str,
        next_digest: str,
        now: datetime,
        *,
        reject: str | None,
        next_access_hash: str | None,
        require_current: bool,
        current_hash: str | None,
    ):
        row = self.get(session_id, lock=True)
        token = self.session.exec(
            select(DshMobileRefreshToken)
            .where(
                DshMobileRefreshToken.token_hash == digest,
                DshMobileRefreshToken.session_id == session_id,
            )
            .execution_options(populate_existing=True)
        ).one_or_none()
        if row is None or token is None:
            return None, "invalid_refresh_token"
        if token.state == "USED":
            self.revoke(row)
            return None, "refresh_token_reused"
        if row.state != "ACTIVE" or token.state == "REVOKED":
            return None, "session_revoked"
        if now >= row.expires_at or now >= token.expires_at:
            self.revoke(row)
            return None, "session_expired"
        if token.state != "ACTIVE" or token.generation >= 9223372036854775807:
            return None, "invalid_refresh_token"
        if reject:
            self.revoke(row)
            return None, reject
        # A missing Redis session fails open, matching the access-token middleware.
        # A different current token means another login replaced this phone.
        if require_current and current_hash is not None and current_hash != row.last_access_token_hash:
            return None, "logged_in_elsewhere"
        token.state = "USED"
        self.session.add(token)
        self.session.add(
            DshMobileRefreshToken(
                token_hash=next_digest,
                tenant_id=row.tenant_id,
                session_id=session_id,
                generation=token.generation + 1,
                state="ACTIVE",
                created_at=now,
                expires_at=row.expires_at,
            )
        )
        row.last_access_token_hash = next_access_hash
        self.session.add(row)
        self.session.flush()
        return self.snapshot(row), None
