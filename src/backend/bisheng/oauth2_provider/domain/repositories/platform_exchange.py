"""Narrow cross-tenant persistence, always bound to verified user and tenant."""

from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.oauth2_provider.domain.models.platform_exchange import OAuth2PlatformExchangeSession, OAuth2UserConsent


class OAuth2PlatformExchangeRepository:
    def __init__(self, session):
        self.session = session

    def get_link(self, session_id, user_id, tenant_id):
        with bypass_tenant_filter():
            return self.session.exec(
                select(OAuth2PlatformExchangeSession).where(
                    OAuth2PlatformExchangeSession.session_id == session_id,
                    OAuth2PlatformExchangeSession.user_id == user_id,
                    OAuth2PlatformExchangeSession.tenant_id == tenant_id,
                )
            ).first()

    def get_consent(self, client, user_id, tenant_id):
        with bypass_tenant_filter():
            return self.session.exec(
                select(OAuth2UserConsent)
                .where(
                    OAuth2UserConsent.client_registration_id == client.id,
                    OAuth2UserConsent.client_id == client.client_id,
                    OAuth2UserConsent.user_id == user_id,
                    OAuth2UserConsent.tenant_id == tenant_id,
                )
                .with_for_update()
            ).first()

    def save_consent(self, client, user_id, tenant_id, scopes):
        with bypass_tenant_filter():
            row = self.get_consent(client, user_id, tenant_id)
            if row is None:
                row = OAuth2UserConsent(
                    client_registration_id=client.id,
                    client_id=client.client_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    scopes=sorted(set(scopes)),
                )
            else:
                row.scopes = sorted(set(row.scopes) | set(scopes))
            self.save(row)

    def revoke_consent(self, client, user_id, tenant_id):
        with bypass_tenant_filter():
            row = self.get_consent(client, user_id, tenant_id)
            if row is not None:
                self.session.delete(row)
                self.session.flush()

    def save(self, row):
        with bypass_tenant_filter():
            self.session.add(row)
            self.session.flush()
