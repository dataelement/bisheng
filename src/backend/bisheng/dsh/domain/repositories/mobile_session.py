"""Short SQL transactions for one phone's refresh-token rotation."""

from datetime import datetime, timedelta
from uuid import uuid4

from loguru import logger
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
    def remember_access_hash(self, session_id: str, access_hash: str | None):
        row = self.get(session_id, lock=True)
        if row is None:
            return False
        row.last_access_token_hash = access_hash
        self.session.add(row)
        self.session.flush()
        return True

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
        grace_seconds: int = 0,
        idle_seconds: int = 1209600,
        absolute_seconds: int = 15552000,
    ):
        """Rotate, or return the unspent successor during the replay grace window.

        Returns ``(snapshot, error, replayed, replaced_access_hash)``. ``replayed``
        is True when this call handed back a successor that was already issued;
        callers must not revoke that successor if publication fails. The last
        value is the access hash this replay overwrote, read under the row lock,
        so a caller that fails to publish restores what was actually replaced
        rather than a value that may have moved since.
        A fresh rotation slides the idle deadline up to the absolute cap.
        """
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
            return None, "invalid_refresh_token", False, None
        if row.state != "ACTIVE" or token.state == "REVOKED":
            return None, "session_revoked", False, None
        absolute_deadline = row.created_at + timedelta(seconds=absolute_seconds)
        if now >= absolute_deadline or now >= row.expires_at:
            self.revoke(row)
            return None, "session_expired", False, None
        if token.state == "USED":
            # Its old deadline must not cut short the unspent successor's replay grace.
            return self._replay_or_revoke(
                row,
                token,
                next_digest,
                now,
                reject=reject,
                next_access_hash=next_access_hash,
                require_current=require_current,
                current_hash=current_hash,
                grace_seconds=grace_seconds,
            )
        if now >= token.expires_at:
            self.revoke(row)
            return None, "session_expired", False, None
        if token.state != "ACTIVE" or token.generation >= 9223372036854775807:
            return None, "invalid_refresh_token", False, None
        if reject:
            self.revoke(row)
            return None, reject, False, None
        # A missing Redis session fails open, matching the access-token middleware.
        # A different current token means another login replaced this phone.
        if self._replaced_elsewhere(require_current, current_hash, row):
            return None, "logged_in_elsewhere", False, None
        renewed = now + timedelta(seconds=idle_seconds)
        if renewed > absolute_deadline:
            renewed = absolute_deadline
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
                expires_at=renewed,
            )
        )
        row.expires_at = renewed
        row.last_access_token_hash = next_access_hash
        self.session.add(row)
        self.session.flush()
        return self.snapshot(row), None, False, None

    def _replay_or_revoke(
        self,
        row,
        token,
        next_digest: str,
        now: datetime,
        *,
        reject: str | None,
        next_access_hash: str | None,
        require_current: bool,
        current_hash: str | None,
        grace_seconds: int,
    ):
        if not self._unspent_successor(row, token, next_digest, now, grace_seconds):
            self.revoke(row)
            return None, "refresh_token_reused", False, None
        # The successor may already be on the phone. Reject the account, but do not
        # revoke it when another login owns Redis: this replay did not issue a new grant.
        if reject:
            self.revoke(row)
            return None, reject, False, None
        if self._replaced_elsewhere(require_current, current_hash, row):
            return None, "logged_in_elsewhere", True, None
        logger.info(
            "mobile refresh grace return session_id={} generation={}",
            row.session_id,
            token.generation + 1,
        )
        replaced_access_hash = row.last_access_token_hash
        row.last_access_token_hash = next_access_hash
        self.session.add(row)
        self.session.flush()
        return self.snapshot(row), None, True, replaced_access_hash

    def _unspent_successor(self, row, token, next_digest: str, now: datetime, grace_seconds: int) -> bool:
        if grace_seconds <= 0 or row.state != "ACTIVE" or now >= row.expires_at:
            return False
        successor = self.session.exec(
            select(DshMobileRefreshToken)
            .where(
                DshMobileRefreshToken.session_id == row.session_id,
                DshMobileRefreshToken.token_hash == next_digest,
                DshMobileRefreshToken.generation == token.generation + 1,
            )
            .execution_options(populate_existing=True)
        ).one_or_none()
        if successor is None or successor.state != "ACTIVE":
            return False
        return now - successor.created_at <= timedelta(seconds=grace_seconds)

    @staticmethod
    def _replaced_elsewhere(require_current: bool, current_hash: str | None, row) -> bool:
        return bool(require_current and current_hash is not None and current_hash != row.last_access_token_hash)
