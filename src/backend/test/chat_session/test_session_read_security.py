"""Session reads must use personal subject, explicit audit or exact typed token."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.common.errcode.http_error import UnAuthorizedError


def actor():
    return SimpleNamespace(user_id=11, tenant_id=7, is_admin=lambda: False)


def test_app_list_filters_foreign_sessions_without_task(monkeypatch):
    from bisheng.chat_session.domain import chat as module

    monkeypatch.setattr(module.UserGroupDao, "get_user_admin_group", lambda _: [])
    monkeypatch.setattr(
        module.MessageSessionDao,
        "filter_session",
        lambda **kwargs: [
            SimpleNamespace(
                chat_id="victim", flow_id="app", user_id=22, tenant_id=7, is_delete=False, api_subject_type=None
            )
        ],
    )
    monkeypatch.setattr(module.MarkRecordDao, "filter_records", lambda **kwargs: [])
    audit = AsyncMock(side_effect=UnAuthorizedError())
    monkeypatch.setattr(module.AuditLogService, "assert_session_in_audit_scope", audit)
    result = ChatSessionService.get_app_chat_list(login_user=actor())
    assert result.list == []
    assert result.total == 0


async def test_audit_reader_retains_read_without_personal_shortcut(monkeypatch):
    from bisheng.chat_session.domain.services import session_read_authorization as policy

    audit = AsyncMock()
    monkeypatch.setattr(policy.AuditLogService, "assert_session_in_audit_scope", audit)
    session = SimpleNamespace(
        chat_id="chat", flow_id="app", tenant_id=7, user_id=22, api_subject_type=None, is_delete=False
    )
    await policy.require_session_read(session, actor())
    assert audit.await_count == 1
    assert audit.await_args.args[0].user_id == 11
    assert audit.await_args.args[1] == "chat"
    assert audit.await_args.kwargs == {"app_id": "app"}


async def test_api_compatibility_owner_needs_explicit_audit(monkeypatch):
    import pytest

    from bisheng.chat_session.domain.services import session_read_authorization as policy

    audit = AsyncMock(side_effect=UnAuthorizedError())
    monkeypatch.setattr(policy.AuditLogService, "assert_session_in_audit_scope", audit)
    session = SimpleNamespace(
        chat_id="chat", flow_id="app", tenant_id=7, user_id=11, api_subject_type="service_account", is_delete=False
    )
    with pytest.raises(UnAuthorizedError):
        await policy.require_session_read(session, actor())
    audit.assert_awaited_once()


async def test_typed_share_is_bound_to_actual_chat_and_tenant():
    import pytest

    from bisheng.chat_session.domain.services.session_read_authorization import require_session_read

    session = SimpleNamespace(chat_id="chat", flow_id="app", flow_type=10, tenant_id=7, user_id=22, is_delete=False)
    share = SimpleNamespace(resource_id="chat", resource_type="workflow", tenant_id=7, meta_data={"flowId": "app"})
    await require_session_read(session, None, share)
    for field, value in [
        ("resource_id", "other"),
        ("tenant_id", 8),
        ("resource_type", "assistant"),
        ("meta_data", {"flowId": "other"}),
    ]:
        original = getattr(share, field)
        setattr(share, field, value)
        with pytest.raises(UnAuthorizedError):
            await require_session_read(session, None, share)
        setattr(share, field, original)
