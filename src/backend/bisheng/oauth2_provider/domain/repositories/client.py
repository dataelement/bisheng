"""Repository for OAuth 2.0 / OIDC client registrations."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.oauth2_provider.domain.models.client import (
    BUILTIN_DSH_CLIENT_ID,
    DEFAULT_GRANT_TYPES,
    DSH_ALLOWED_SCOPES,
    OAuth2Client,
)


class OAuth2ClientRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_client_id(self, client_id: str) -> OAuth2Client | None:
        with bypass_tenant_filter():
            return self.session.exec(select(OAuth2Client).where(OAuth2Client.client_id == client_id)).first()

    def list_clients(
        self, *, keyword: str | None = None, page: int = 1, page_size: int = 50
    ) -> tuple[list[OAuth2Client], int]:
        with bypass_tenant_filter():
            stmt = select(OAuth2Client)
            count_stmt = select(func.count()).select_from(OAuth2Client)
            if keyword:
                pattern = f"%{keyword.strip()}%"
                cond = OAuth2Client.client_id.ilike(pattern) | OAuth2Client.client_name.ilike(pattern)
                stmt = stmt.where(cond)
                count_stmt = count_stmt.where(cond)
            total = int(self.session.exec(count_stmt).one() or 0)
            rows = list(
                self.session.exec(
                    stmt.order_by(OAuth2Client.is_builtin.desc(), OAuth2Client.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                ).all()
            )
            return rows, total

    def create(self, client: OAuth2Client) -> OAuth2Client:
        with bypass_tenant_filter():
            now = datetime.utcnow()
            if client.create_time is None:
                client.create_time = now
            client.update_time = now
            self.session.add(client)
            self.session.flush()
            self.session.refresh(client)
            return client

    def save(self, client: OAuth2Client) -> OAuth2Client:
        with bypass_tenant_filter():
            client.update_time = datetime.utcnow()
            self.session.add(client)
            self.session.flush()
            self.session.refresh(client)
            return client

    def delete(self, client: OAuth2Client) -> None:
        with bypass_tenant_filter():
            self.session.delete(client)
            self.session.flush()

    def ensure_builtin_dsh_client(self) -> OAuth2Client:
        existing = self.get_by_client_id(BUILTIN_DSH_CLIENT_ID)
        if existing is not None:
            return existing
        builtin = OAuth2Client(
            client_id=BUILTIN_DSH_CLIENT_ID,
            client_name="BiSheng Desktop",
            description="Built-in public PKCE client for BiSheng Desktop native login.",
            client_type="public",
            client_secret_hash=None,
            redirect_uris=["http://127.0.0.1/dsh/callback"],
            allow_loopback_port=True,
            allowed_scopes=list(DSH_ALLOWED_SCOPES),
            grant_types=list(DEFAULT_GRANT_TYPES),
            require_pkce=True,
            require_consent=True,
            enabled=True,
            is_builtin=True,
            access_token_ttl=300,
            refresh_token_ttl=1209600,
        )
        return self.create(builtin)
