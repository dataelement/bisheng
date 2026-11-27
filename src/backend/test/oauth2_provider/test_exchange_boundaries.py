"""Additional storage, expiry and diagnostic boundary tests."""

from datetime import datetime, timedelta

import pytest
from loguru import logger
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlmodel import select

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.oauth2_provider import OAuth2InvalidAccessTokenError
from bisheng.core.database.model_discovery import discover_sqlmodel_module_names
from bisheng.oauth2_provider.domain.models.exchange import OAuth2ExchangePolicy, OAuth2ExchangeSession
from bisheng.oauth2_provider.domain.models.platform_exchange import OAuth2PlatformExchangeSession, OAuth2UserConsent
from bisheng.oauth2_provider.domain.models.session import OAuth2Session
from bisheng.oauth2_provider.domain.schemas.client import OAuth2ClientCreate
from bisheng.oauth2_provider.domain.schemas.exchange import EXCHANGE_GRANT_TYPE
from test.oauth2_provider.test_exchange import exchange_env, oauth2_env  # noqa: F401


@pytest.mark.parametrize("dialect_name", ["mysql", "dm"])
def test_models_discovered_and_dual_database_ddl(dialect_name):
    """AC-17: discovery/DDL compile, with an explicit skip if optional DM dialect is absent."""
    assert {
        "bisheng.oauth2_provider.domain.models.exchange",
        "bisheng.oauth2_provider.domain.models.platform_exchange",
    } <= set(discover_sqlmodel_module_names())
    dialect = mysql.dialect() if dialect_name == "mysql" else pytest.importorskip("dmSQLAlchemy.dmpython").dialect()
    for model in (OAuth2ExchangePolicy, OAuth2ExchangeSession, OAuth2PlatformExchangeSession, OAuth2UserConsent):
        assert model.__tablename__ in str(CreateTable(model.__table__).compile(dialect=dialect)).lower()
        for index in model.__table__.indexes:
            assert str(CreateIndex(index).compile(dialect=dialect))


@pytest.mark.usefixtures("exchange_env")
async def test_parent_expiry_and_missing_link(request):
    """AC-08/15: source expiry bounds child; missing link never downgrades to ordinary login."""
    runtime, params, parent, _ = request.getfixturevalue("exchange_env")
    with runtime.auth._session_factory() as db:
        row = db.exec(select(OAuth2Session).where(OAuth2Session.session_id == parent.session_id)).one()
        row.expires_at = datetime.utcnow() + timedelta(seconds=25)
        db.add(row)
    result = await runtime.exchange.exchange_token(**params)
    assert 0 < result["expires_in"] <= 25
    with runtime.auth._session_factory() as db:
        row = db.exec(
            select(OAuth2ExchangeSession).where(OAuth2ExchangeSession.session_id == result["session_id"])
        ).one()
        db.delete(row)
    with pytest.raises(OAuth2InvalidAccessTokenError):
        await runtime.auth.userinfo("Bearer " + result["access_token"])


@pytest.mark.usefixtures("exchange_env")
async def test_default_grants_and_public_source(request):
    """AC-02/17: no default grant and no public-client exchange."""
    runtime, params, _, _ = request.getfixturevalue("exchange_env")
    public = await runtime.clients.create_client(
        OAuth2ClientCreate(
            client_id="public-source",
            client_name="Public",
            client_type="public",
            redirect_uris=["https://public.example/cb"],
            grant_types=["authorization_code", EXCHANGE_GRANT_TYPE],
        )
    )
    with pytest.raises(BaseErrorCode) as exc:
        await runtime.exchange.exchange_token(**{**params, "client_id": public.client.client_id, "client_secret": None})
    assert exc.value.code == 28104
    normal = await runtime.clients.get_client("target-b")
    assert EXCHANGE_GRANT_TYPE not in normal.grant_types


@pytest.mark.usefixtures("exchange_env")
async def test_redacted_dependency_logs(request):
    """AC-13: diagnostic stack locations do not contain credential values."""
    runtime, params, _, _ = request.getfixturevalue("exchange_env")
    secret = "private-fault-marker"

    async def failed(*args):
        raise RuntimeError(secret)

    runtime.exchange._identity_lookup = failed
    logs = []
    sink = logger.add(lambda message: logs.append(str(message)))
    try:
        with pytest.raises(BaseErrorCode):
            await runtime.exchange.exchange_token(**params)
    finally:
        logger.remove(sink)
    for value in [secret, params["subject_token"], params["client_secret"]]:
        assert value not in "".join(logs)
