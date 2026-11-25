"""Repository for OAuth 2.0 sessions and rotating refresh tokens."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import case, update
from sqlmodel import Session, select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.oauth2_provider.domain.models.session import OAuth2RefreshToken, OAuth2Session


class OAuth2SessionRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_session(
        self,
        *,
        client_id: str,
        tenant_id: int,
        user_id: int,
        scope: str,
        refresh_token_hash: str | None,
        refresh_ttl_seconds: int,
        access_ttl_seconds: int,
        device_name: str | None = None,
        now: datetime | None = None,
    ) -> OAuth2Session:
        ts = now or datetime.utcnow()
        refresh_expires_at = ts + timedelta(seconds=refresh_ttl_seconds)
        session_ttl = max(access_ttl_seconds, refresh_ttl_seconds if refresh_token_hash else 0)
        expires_at = ts + timedelta(seconds=session_ttl)
        record = OAuth2Session(
            session_id=str(uuid4()),
            client_id=client_id,
            tenant_id=tenant_id,
            user_id=user_id,
            scope=scope,
            state="ACTIVE",
            device_name=device_name,
            created_at=ts,
            expires_at=expires_at,
            revoked_at=None,
        )
        with bypass_tenant_filter():
            self.session.add(record)
            if refresh_token_hash:
                self.session.add(
                    OAuth2RefreshToken(
                        token_hash=refresh_token_hash,
                        session_id=record.session_id,
                        client_id=client_id,
                        tenant_id=tenant_id,
                        generation=1,
                        state="ACTIVE",
                        used_at=None,
                        expires_at=refresh_expires_at,
                    )
                )
            self.session.flush()
            return record

    def get_session(self, session_id: str) -> OAuth2Session | None:
        with bypass_tenant_filter():
            return self.session.exec(select(OAuth2Session).where(OAuth2Session.session_id == session_id)).first()

    def get_refresh_token(self, token_hash: str) -> OAuth2RefreshToken | None:
        with bypass_tenant_filter():
            return self.session.exec(
                select(OAuth2RefreshToken).where(OAuth2RefreshToken.token_hash == token_hash)
            ).first()

    def rotate_refresh_token(
        self,
        *,
        old_token: OAuth2RefreshToken,
        new_token_hash: str,
        refresh_ttl_seconds: int,
        access_ttl_seconds: int,
        now: datetime | None = None,
    ) -> tuple[OAuth2Session, OAuth2RefreshToken] | None:
        ts = now or datetime.utcnow()
        new_expires_at = ts + timedelta(seconds=refresh_ttl_seconds)
        session_expires_at = ts + timedelta(seconds=max(access_ttl_seconds, refresh_ttl_seconds))
        # Every mutation locks the family row first. Conditional UPDATE is a
        # current read on both MySQL and DM8, including under repeatable read.
        # A revoked/expired family cannot be resurrected by a stale ORM object.
        locked = self.session.execute(
            update(OAuth2Session)
            .where(
                OAuth2Session.session_id == old_token.session_id,
                OAuth2Session.state == "ACTIVE",
                OAuth2Session.expires_at > ts,
            )
            .values(
                expires_at=case(
                    (OAuth2Session.expires_at > session_expires_at, OAuth2Session.expires_at),
                    else_=session_expires_at,
                )
            )
            .execution_options(synchronize_session=False)
        )
        if locked.rowcount != 1:
            return None
        consumed = self.session.execute(
            update(OAuth2RefreshToken)
            .where(
                OAuth2RefreshToken.token_hash == old_token.token_hash,
                OAuth2RefreshToken.session_id == old_token.session_id,
                OAuth2RefreshToken.state == "ACTIVE",
                OAuth2RefreshToken.expires_at > ts,
            )
            .values(state="USED", used_at=ts)
            .execution_options(synchronize_session=False)
        )
        if consumed.rowcount != 1:
            # A concurrent winner may have committed a successor already.
            # Persist family revocation before the service raises invalid_grant.
            self.revoke_session(old_token.session_id, now=ts)
            return None
        with bypass_tenant_filter():
            session_row = self.get_session(old_token.session_id)
            successor = OAuth2RefreshToken(
                token_hash=new_token_hash,
                session_id=session_row.session_id,
                client_id=session_row.client_id,
                tenant_id=session_row.tenant_id,
                generation=int(old_token.generation) + 1,
                state="ACTIVE",
                used_at=None,
                expires_at=new_expires_at,
            )
            self.session.add(successor)
            self.session.flush()
            return session_row, successor

    def revoke_session(self, session_id: str, *, now: datetime | None = None) -> bool:
        ts = now or datetime.utcnow()
        result = self.session.execute(
            update(OAuth2Session)
            .where(OAuth2Session.session_id == session_id)
            .values(state="REVOKED", revoked_at=ts)
            .execution_options(synchronize_session=False)
        )
        self.session.execute(
            update(OAuth2RefreshToken)
            .where(OAuth2RefreshToken.session_id == session_id)
            .values(state="REVOKED")
            .execution_options(synchronize_session=False)
        )
        self.session.flush()
        return result.rowcount == 1

    def revoke_by_client_id(self, client_id: str, *, now: datetime | None = None) -> int:
        ts = now or datetime.utcnow()
        result = self.session.execute(
            update(OAuth2Session)
            .where(OAuth2Session.client_id == client_id)
            .values(state="REVOKED", revoked_at=ts)
            .execution_options(synchronize_session=False)
        )
        self.session.execute(
            update(OAuth2RefreshToken)
            .where(OAuth2RefreshToken.client_id == client_id)
            .values(state="REVOKED")
            .execution_options(synchronize_session=False)
        )
        self.session.flush()
        return result.rowcount
