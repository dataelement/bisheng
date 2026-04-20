"""F017 unit tests — ChatMessageService derived-data tenant attribution (T12).

Verifies INV-T13: every ChatMessage row carries the user's leaf tenant, not
the resource tenant of the assistant/workflow being conversed with.

Mocks the DAO layer + ContextVar so this module runs without a live DB.
"""

from __future__ import annotations

# F017: pre-mock the ``bisheng.api`` chain — importing
# chat_message_service pulls ``bisheng.api.services.chat_imp`` which
# triggers the full bisheng.api router init. That clashes with
# conftest.py's premock_import_chain (which MagicMocks
# ``bisheng.common.services``), so we defensively stub the api modules
# ourselves. Same pattern used in F011/F013 tests.
import sys as _sys  # noqa: E402
from unittest.mock import MagicMock as _MagicMock  # noqa: E402

# conftest.py premocks ``bisheng.common.services`` as MagicMock which
# breaks later ``from bisheng.common.services.base import ...`` lookups.
# Drop that mock before our real imports so the package loads normally;
# conftest's other premocks (errcodes, database models) remain untouched.
for _common_services_mod in (
    'bisheng.common.services',
    'bisheng.common.services.config_service',
    'bisheng.common.services.telemetry',
    'bisheng.common.services.telemetry.telemetry_service',
):
    _sys.modules.pop(_common_services_mod, None)

for _m in (
    'bisheng.api',
    'bisheng.api.services',
    'bisheng.api.services.chat_imp',
    'bisheng.api.v1',
    'bisheng.api.v1.schemas',
):
    _sys.modules.setdefault(_m, _MagicMock())

from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402

from bisheng.chat_session.domain.services.chat_message_service import (  # noqa: E402
    ChatMessageService,
    _resolve_leaf_tenant_id,
)
from bisheng.common.errcode.tenant_sharing import TenantContextMissingError  # noqa: E402
from bisheng.core.context.tenant import current_tenant_id  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────


def _login_user(user_id: int = 100, tenant_id: int | None = 5):
    u = MagicMock()
    u.user_id = user_id
    u.tenant_id = tenant_id
    u.user_name = 'tester'
    return u


# ── _resolve_leaf_tenant_id ──────────────────────────────────────


def test_resolve_leaf_prefers_context_over_login_user():
    """ContextVar (5) wins over login_user.tenant_id (7)."""
    u = _login_user(tenant_id=7)
    token = current_tenant_id.set(5)
    try:
        assert _resolve_leaf_tenant_id(u) == 5
    finally:
        current_tenant_id.reset(token)


def test_resolve_leaf_falls_back_to_login_user_when_context_none():
    """When ContextVar is unset, login_user.tenant_id supplies the value."""
    u = _login_user(tenant_id=7)
    # ContextVar default is None (no ``set`` call)
    assert _resolve_leaf_tenant_id(u) == 7


def test_resolve_leaf_raises_when_both_missing():
    """F017 AC-11: refuse to fabricate a tenant when nothing is available."""
    with pytest.raises(TenantContextMissingError):
        _resolve_leaf_tenant_id(None)


def test_resolve_leaf_raises_when_login_user_has_no_tenant():
    """login_user without a tenant_id attribute must not paper over a None."""
    u = MagicMock()
    u.user_id = 1
    u.tenant_id = None
    with pytest.raises(TenantContextMissingError):
        _resolve_leaf_tenant_id(u)


# ── acreate ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acreate_writes_leaf_tenant_id_from_context():
    """acreate stamps ChatMessage.tenant_id = get_current_tenant_id()."""
    captured = {}

    def _fake_insert(msgs):
        captured['msgs'] = msgs
        return msgs

    token = current_tenant_id.set(5)
    try:
        with patch(
            'bisheng.chat_session.domain.services.chat_message_service.ChatMessageDao.insert_batch',
            side_effect=_fake_insert,
        ):
            result = await ChatMessageService.acreate(
                user_id=100, chat_id='c1', flow_id='f1', message='hi',
                login_user=_login_user(tenant_id=7),  # should be ignored; context wins
            )
    finally:
        current_tenant_id.reset(token)

    assert result.tenant_id == 5
    assert captured['msgs'][0].tenant_id == 5


@pytest.mark.asyncio
async def test_acreate_raises_when_no_tenant_anywhere():
    """Context=None + login_user=None → 19504 (AC-11)."""
    with pytest.raises(TenantContextMissingError):
        await ChatMessageService.acreate(
            user_id=100, chat_id='c1', flow_id='f1', message='hi',
            login_user=None,
        )


# ── add_qa_messages ──────────────────────────────────────────────


def test_add_qa_messages_stamps_both_messages_with_leaf_tenant():
    """Both human + bot ChatMessage rows carry tenant_id = leaf."""
    captured = {}

    def _fake_insert(msgs):
        captured['msgs'] = msgs
        return msgs

    data = MagicMock()
    data.flow_id = 'flow-1'
    data.chat_id = 'chat-1'
    data.human_message = 'question?'
    data.answer_message = 'answer!'

    token = current_tenant_id.set(5)
    try:
        with patch(
            'bisheng.chat_session.domain.services.chat_message_service.ChatMessageDao.insert_batch',
            side_effect=_fake_insert,
        ), patch(
            'bisheng.chat_session.domain.services.chat_message_service.MessageSessionDao.update_sensitive_status',
        ), patch(
            'bisheng.chat_session.domain.services.chat_message_service.FlowDao.get_flow_by_id',
            return_value=None,
        ), patch(
            'bisheng.chat_session.domain.chat.ChatSessionService.get_or_create_session',
        ):
            ChatMessageService.add_qa_messages(data, _login_user(tenant_id=7), request_ip='1.2.3.4')
    finally:
        current_tenant_id.reset(token)

    msgs = captured['msgs']
    assert len(msgs) == 2
    assert all(m.tenant_id == 5 for m in msgs)  # context wins over login_user(7)
