"""Persistence operations for platform policies and tenant-bound exchange links."""

from sqlalchemy import func
from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.oauth2_provider.domain.models.exchange import OAuth2ExchangePolicy, OAuth2ExchangeSession


class OAuth2ExchangeRepository:
    def __init__(self, session):
        self.session = session

    def get_policy(self, source, target):
        with bypass_tenant_filter():
            return self.session.exec(
                select(OAuth2ExchangePolicy).where(
                    OAuth2ExchangePolicy.source_client_id == source, OAuth2ExchangePolicy.target_client_id == target
                )
            ).first()

    def list_policies(self, source, page, page_size):
        with bypass_tenant_filter():
            query = select(OAuth2ExchangePolicy)
            count = select(func.count()).select_from(OAuth2ExchangePolicy)
            if source:
                query = query.where(OAuth2ExchangePolicy.source_client_id == source)
                count = count.where(OAuth2ExchangePolicy.source_client_id == source)
            rows = self.session.exec(
                query.order_by(OAuth2ExchangePolicy.source_client_id, OAuth2ExchangePolicy.target_client_id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return list(rows), self.session.exec(count).one()

    def get_link(self, session_id, tenant_id=None, user_id=None):
        with bypass_tenant_filter():
            query = select(OAuth2ExchangeSession).where(OAuth2ExchangeSession.session_id == session_id)
            if tenant_id is not None:
                query = query.where(OAuth2ExchangeSession.tenant_id == tenant_id)
            if user_id is not None:
                query = query.where(OAuth2ExchangeSession.user_id == user_id)
            return self.session.exec(query).first()

    def save(self, row):
        with bypass_tenant_filter():
            self.session.add(row)
            self.session.flush()
            self.session.refresh(row)
            return row
