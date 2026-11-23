"""Repository for OAuth 2.0 sessions and rotating refresh tokens."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

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
        device_name: str | None = None,
        now: datetime | None = None,
    ) -> OAuth2Session:
        ts = now or datetime.utcnow()
        expires_at = ts + timedelta(seconds=refresh_ttl_seconds)
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
                        expires_at=expires_at,
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
        now: datetime | None = None,
    ) -> tuple[OAuth2Session, OAuth2RefreshToken]:
        ts = now or datetime.utcnow()
        with bypass_tenant_filter():
            session_row = self.session.exec(
                select(OAuth2Session).where(OAuth2Session.session_id == old_token.session_id)
            ).first()
            if session_row is None:
                raise ValueError("OAuth2 session missing")
            old_token.state = "USED"
            old_token.used_at = ts
            self.session.add(old_token)
            new_expires_at = ts + timedelta(seconds=refresh_ttl_seconds)
            session_row.expires_at = new_expires_at
            self.session.add(session_row)
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
        with bypass_tenant_filter():
            session_row = self.session.exec(select(OAuth2Session).where(OAuth2Session.session_id == session_id)).first()
            if session_row is None:
                return False
            session_row.state = "REVOKED"
            session_row.revoked_at = ts
            self.session.add(session_row)
            tokens = self.session.exec(
                select(OAuth2RefreshToken).where(OAuth2RefreshToken.session_id == session_id)
            ).all()
            for token in tokens:
                token.state = "REVOKED"
                self.session.add(token)
            self.session.flush()
            return True

    def revoke_by_client_id(self, client_id: str, *, now: datetime | None = None) -> int:
        ts = now or datetime.utcnow()
        with bypass_tenant_filter():
            sessions = list(
                self.session.exec(
                    select(OAuth2Session).where(
                        OAuth2Session.client_id == client_id,
                        OAuth2Session.state == "ACTIVE",
                    )
                ).all()
            )
            for row in sessions:
                row.state = "REVOKED"
                row.revoked_at = ts
                self.session.add(row)
            tokens = self.session.exec(
                select(OAuth2RefreshToken).where(
                    OAuth2RefreshToken.client_id == client_id,
                    OAuth2RefreshToken.state == "ACTIVE",
                )
            ).all()
            for token in tokens:
                token.state = "REVOKED"
                self.session.add(token)
            self.session.flush()
            return len(sessions)
