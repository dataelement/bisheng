"""Share-link reads must survive tenant scoping, and a stale token must not 404.

Two regressions are locked down here.

1. ``bypass_tenant_filter_if`` — a share link is authorized by its secret token,
   and recipients are routinely in another tenant than the owner. Every row
   behind a share (``message``, ``session``, ``linsight_session_version``,
   ``linsight_execute_task``) is tenant-aware, so the auto-injected
   ``tenant_id IN (leaf, root)`` hid them from a recipient in a different child
   tenant. The endpoints then saw an empty result, skipped their authorization
   branch and answered ``200 []`` — the recipient got a blank page, no error.

2. ``header_share_token_parser`` — its declared contract is
   ``Optional[ShareLink]``, but the service it calls raises ``NotFoundError`` for
   an unknown / revoked token. Letting that propagate made ANY request carrying a
   stale ``share-token`` header fail wholesale, the session owner's own request
   included (verified against a live env: owner + bogus header → 404, owner
   without the header → 200).
"""

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import Column, Integer, String, create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.config.multi_tenant import MultiTenantConf
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    bypass_tenant_filter_if,
    current_tenant_id,
    is_tenant_filter_bypassed,
    set_current_tenant_id,
    set_visible_tenant_ids,
    visible_tenant_ids,
)

# Pre-mock the modules whose import chain would otherwise drag in real infra.
_MOCK_MODULES = [
    "bisheng.common.services",
    "bisheng.common.services.config_service",
    "bisheng.common.services.telemetry",
    "bisheng.common.services.telemetry.telemetry_service",
]
for _m in _MOCK_MODULES:
    if _m not in sys.modules:
        _mock = MagicMock()
        if _m == "bisheng.common.services.config_service":
            _mock.settings = MagicMock()
            _mock.settings.multi_tenant = MultiTenantConf(enabled=False)
        sys.modules[_m] = _mock


class _SharedRow(SQLModelSerializable, table=True):
    """Stands in for any tenant-aware row reachable through a share link."""

    __tablename__ = "_share_link_test_row"
    id: int = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))
    name: str = Field(sa_column=Column(String(64), nullable=False))
    tenant_id: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))


@pytest.fixture()
def filter_engine():
    from bisheng.core.database import tenant_filter

    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _SharedRow.__table__.create(engine, checkfirst=True)
    tenant_filter.register_tenant_filter_events()

    yield engine

    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    engine.dispose()


@pytest.fixture()
def session(filter_engine):
    connection = filter_engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection)
    yield sess
    sess.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture()
def owner_row_in_other_child_tenant(session):
    """One row owned by child tenant 7; the reader will live in child tenant 5."""
    with bypass_tenant_filter():
        session.add(_SharedRow(name="owner_row", tenant_id=7))
        session.commit()
    return "owner_row"


@pytest.fixture()
def reader_in_child_tenant_5():
    """Recipient context: leaf tenant 5, so visible = {5, root}. Excludes 7."""
    tenant_token = set_current_tenant_id(5)
    visible_token = set_visible_tenant_ids(frozenset({5, 1}))
    yield
    visible_tenant_ids.reset(visible_token)
    current_tenant_id.reset(tenant_token)


class TestCrossTenantShareRead:
    def test_read_without_share_token_stays_filtered(
        self, session, owner_row_in_other_child_tenant, reader_in_child_tenant_5
    ):
        """No capability → strict scoping. Proves the widening is opt-in, not blanket."""
        with bypass_tenant_filter_if(False):
            rows = session.exec(select(_SharedRow)).all()

        assert rows == []

    def test_read_with_share_token_sees_the_owner_row(
        self, session, owner_row_in_other_child_tenant, reader_in_child_tenant_5
    ):
        """This is the regression: before the fix the recipient got an empty list
        and the endpoint answered 200 [] instead of the shared conversation."""
        with bypass_tenant_filter_if(True):
            rows = session.exec(select(_SharedRow)).all()

        assert [row.name for row in rows] == ["owner_row"]

    def test_widening_is_scoped_to_the_block(self, session, owner_row_in_other_child_tenant, reader_in_child_tenant_5):
        """Leaving the block must restore filtering — a leaked bypass would turn
        every later query in the request into a cross-tenant read."""
        with bypass_tenant_filter_if(True):
            assert is_tenant_filter_bypassed() is True

        assert is_tenant_filter_bypassed() is False
        assert session.exec(select(_SharedRow)).all() == []


class TestHeaderShareTokenParser:
    async def test_missing_header_returns_none(self):
        from bisheng.share_link.api.dependencies import header_share_token_parser

        service = MagicMock()
        service.get_share_link_by_token = AsyncMock()

        assert await header_share_token_parser(share_token=None, share_link_service=service) is None
        service.get_share_link_by_token.assert_not_awaited()

    async def test_unknown_token_returns_none_instead_of_raising(self):
        """A stale header means "no share grant", not "this request is a 404"."""
        from bisheng.common.errcode.http_error import NotFoundError
        from bisheng.share_link.api.dependencies import header_share_token_parser

        service = MagicMock()
        service.get_share_link_by_token = AsyncMock(side_effect=NotFoundError())

        result = await header_share_token_parser(share_token="BOGUSTOKEN123", share_link_service=service)

        assert result is None

    async def test_active_token_returns_the_share_link(self):
        from bisheng.share_link.api.dependencies import header_share_token_parser

        share_link = MagicMock()
        service = MagicMock()
        service.get_share_link_by_token = AsyncMock(return_value=share_link)

        result = await header_share_token_parser(share_token="tok", share_link_service=service)

        assert result is share_link


class TestShareTokenAuthorizationStillGates:
    """The widened read must not become an authorization hole.

    Widening happens BEFORE the owner / share_link check, so these cases are
    exactly what stops "any valid token + any conversation id" from working.
    Reached only once the read succeeds, which is why they matter more now:
    before the widening a cross-tenant caller fell into the empty-result
    short-circuit and never got here.
    """

    CHAT_ID = "conv-shared"
    OTHER_CHAT_ID = "conv-not-shared"

    @staticmethod
    def _message_owned_by(user_id: int):
        message = MagicMock()
        message.user_id = user_id
        return message

    @pytest.fixture()
    def endpoints(self, monkeypatch):
        from bisheng.workstation.api.endpoints import chat as chat_endpoints

        dao = MagicMock()
        dao.aget_messages_by_chat_id = AsyncMock(return_value=[self._message_owned_by(1)])
        monkeypatch.setattr(chat_endpoints, "ChatMessageDao", dao)
        # Formatters are irrelevant here; keep the authorized path cheap so the
        # assertions speak only about the permission branch.
        monkeypatch.setattr(chat_endpoints, "_drop_legacy_sibling_branches", lambda msgs: msgs)
        monkeypatch.setattr(chat_endpoints, "_is_new_format", lambda msg: False)
        monkeypatch.setattr(chat_endpoints, "_convert_legacy_message", lambda msg: {"ok": True})
        return chat_endpoints

    def _share_link_for(self, resource_id: str):
        share_link = MagicMock()
        share_link.resource_id = resource_id
        return share_link

    async def test_token_for_another_conversation_is_rejected(self, endpoints):
        reader = MagicMock()
        reader.user_id = 999  # not the owner

        result = await endpoints.get_agent_chat_history(
            conversationId=self.OTHER_CHAT_ID,
            login_user=reader,
            share_link=self._share_link_for(self.CHAT_ID),
        )

        assert result.status_code == 403

    async def test_no_token_at_all_is_rejected_for_a_non_owner(self, endpoints):
        reader = MagicMock()
        reader.user_id = 999

        result = await endpoints.get_agent_chat_history(
            conversationId=self.CHAT_ID,
            login_user=reader,
            share_link=None,
        )

        assert result.status_code == 403

    async def test_matching_token_lets_a_non_owner_through(self, endpoints):
        reader = MagicMock()
        reader.user_id = 999

        result = await endpoints.get_agent_chat_history(
            conversationId=self.CHAT_ID,
            login_user=reader,
            share_link=self._share_link_for(self.CHAT_ID),
        )

        assert result.status_code == 200
        assert result.data == [{"ok": True}]
