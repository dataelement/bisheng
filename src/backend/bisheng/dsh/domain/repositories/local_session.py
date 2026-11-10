"""Short SQL transactions for desktop credential rotation and ownership."""

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

from loguru import logger
from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter, strict_tenant_filter
from bisheng.dsh.domain.models.local_session import (
    ABSOLUTE_SESSION_POLICY,
    SLIDING_SESSION_POLICY,
    DshRefreshToken,
    DshSession,
)


class DshSessionRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def snapshot(row):
        # SQLModelSerializable.model_dump normalizes timestamps to JSON strings.
        # Transaction results retain native datetimes until the HTTP boundary.
        return {name: getattr(row, name) for name in type(row).model_fields}

    def locate_refresh(self, digest: str):
        # A random credential digest is the only global lookup. Services establish
        # the returned tenant before any identity lookup, lock or mutation.
        with bypass_tenant_filter():
            row = self.session.exec(
                select(DshSession.tenant_id, DshSession.user_id, DshSession.session_id, DshSession.expires_at)
                .join(DshRefreshToken, DshRefreshToken.session_id == DshSession.session_id)
                .where(DshRefreshToken.token_hash == digest, DshRefreshToken.tenant_id == DshSession.tenant_id)
            ).first()
            return dict(zip(("tenant_id", "user_id", "session_id", "expires_at"), row, strict=True)) if row else None

    @strict_tenant_filter()
    def get(self, session_id: str, *, lock=False):
        statement = select(DshSession).where(DshSession.session_id == session_id)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return self.session.exec(statement).one_or_none()

    def create(
        self, *, tenant_id, user_id, auth_id, device_label, client_version, expires_at, digest, now, idle_seconds=None
    ):
        row = DshSession(
            session_id=str(uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            auth_id=auth_id,
            device_label=device_label,
            client_version=client_version,
            created_at=now,
            expires_at=expires_at,
            expiry_policy=SLIDING_SESSION_POLICY if idle_seconds is not None else ABSOLUTE_SESSION_POLICY,
            idle_ttl_seconds=idle_seconds,
            last_activity_at=now if idle_seconds is not None else None,
        )
        self.session.add(row)
        self.session.add(
            DshRefreshToken(
                token_hash=digest,
                tenant_id=tenant_id,
                session_id=row.session_id,
                generation=1,
                expires_at=expires_at,
            )
        )
        self.session.flush()
        return self.snapshot(row)

    @strict_tenant_filter()
    def revoke(self, row):
        # The session is the authority for every generation. Do not load an
        # indefinitely growing token chain into a logout/replay transaction.
        row.state = "REVOKED"
        self.session.add(row)

    @strict_tenant_filter()
    def record_activity(self, principal, clock: Callable[[], datetime], *, idle_seconds: int, migrate_existing: bool):
        row = self.get(principal.session_id, lock=True)
        now = clock()
        if row is None or (str(row.user_id), row.version) != (principal.user_id, principal.session_version):
            return None, "invalid_access_token"
        if row.state != "ACTIVE":
            return None, "session_revoked"
        if now >= row.expires_at:
            return None, "session_expired"
        if row.expiry_policy == ABSOLUTE_SESSION_POLICY:
            if not migrate_existing:
                return self.snapshot(row), None
            row.expiry_policy = SLIDING_SESSION_POLICY
            row.idle_ttl_seconds = idle_seconds
        if row.expiry_policy != SLIDING_SESSION_POLICY or not row.idle_ttl_seconds or row.idle_ttl_seconds < 1:
            raise ValueError("Invalid stored desktop session expiry policy")
        row.last_activity_at = max(row.last_activity_at or now, now)
        row.expires_at = row.last_activity_at + timedelta(seconds=row.idle_ttl_seconds)
        self.session.add(row)
        for token in self.session.exec(
            select(DshRefreshToken).where(
                DshRefreshToken.session_id == row.session_id,
                DshRefreshToken.state == "ACTIVE",
            )
        ).all():
            token.expires_at = row.expires_at
            self.session.add(token)
        self.session.flush()
        return self.snapshot(row), None

    @strict_tenant_filter()
    def rotate(
        self, session_id: str, digest: str, next_digest: str, clock: Callable[[], datetime], grace_seconds: int = 0
    ):
        row = self.get(session_id, lock=True)
        token = self.session.exec(
            select(DshRefreshToken)
            .where(
                DshRefreshToken.token_hash == digest,
                DshRefreshToken.session_id == session_id,
            )
            .execution_options(populate_existing=True)
        ).one_or_none()
        # Waiting for the row lock must not let a pre-expiry timestamp revive an
        # already expired session or extend a consumed-token recovery window.
        now = clock()
        if row is None or token is None:
            return None, "invalid_refresh_token"
        # Check the shared authority before handling any historical generation.
        if row.state != "ACTIVE":
            return None, "session_revoked"
        if now >= row.expires_at:
            return None, "session_expired"
        if token.state == "USED":
            if self._return_unspent_successor(row, token, next_digest, now, grace_seconds):
                logger.info(
                    "dsh refresh grace return session_id={} generation={}",
                    row.session_id,
                    token.generation + 1,
                )
                return self.snapshot(row), None
            self.revoke(row)
            return None, "refresh_token_reused"
        if row.expiry_policy == ABSOLUTE_SESSION_POLICY and now >= token.expires_at:
            return None, "session_expired"
        if token.state != "ACTIVE" or token.generation >= 9223372036854775807:
            return None, "invalid_refresh_token"
        token.state = "USED"
        token.used_at = now
        self.session.add(token)
        self.session.add(
            DshRefreshToken(
                token_hash=next_digest,
                tenant_id=row.tenant_id,
                session_id=session_id,
                generation=token.generation + 1,
                expires_at=row.expires_at,
            )
        )
        self.session.flush()
        return self.snapshot(row), None

    def _return_unspent_successor(self, row, token, next_digest: str, now: datetime, grace_seconds: int) -> bool:
        """Return the already issued successor when the client never received it.

        The successor digest is derived from the presented token, so a retry names
        the same row. Returning it leaves the database unchanged.
        """
        if (
            grace_seconds <= 0
            or token.used_at is None
            or now - token.used_at > timedelta(seconds=grace_seconds)
            or row.state != "ACTIVE"
            or now >= row.expires_at
            or (row.expiry_policy == ABSOLUTE_SESSION_POLICY and now >= token.expires_at)
        ):
            return False
        successor = self.session.exec(
            select(DshRefreshToken)
            .where(
                DshRefreshToken.session_id == row.session_id,
                DshRefreshToken.token_hash == next_digest,
                DshRefreshToken.generation == token.generation + 1,
            )
            .execution_options(populate_existing=True)
        ).one_or_none()
        return successor is not None and successor.state == "ACTIVE"

    @strict_tenant_filter()
    def page(self, user_id, *, cursor=None, limit=20):
        statement = select(DshSession).where(DshSession.user_id == user_id)
        if cursor:
            statement = statement.where(DshSession.session_id > cursor)
        rows = list(self.session.exec(statement.order_by(DshSession.session_id).limit(limit + 1)).all())
        return {
            "items": [self.snapshot(row) for row in rows[:limit]],
            "has_more": len(rows) > limit,
            "next_cursor": rows[limit - 1].session_id if len(rows) > limit else None,
        }
