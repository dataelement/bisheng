"""F052 T208a (service half) — ``get_instance`` admits by entry, like ``get_logs``.

The instance view used to be "owner, tenant administrator, or super admin" on
every door. That is right for the platform detail page and wrong for a
credential door: a developer key acts for its resource owner, so letting an
administrator's key read every application's runtime state widens the open-API
surface past what the key's holder was ever granted (AC-34 / AC-35).

Owner-only is a **business** pre-check, never an F048 check — the permission
runtime short-circuits administrators to ALLOW and cannot express it at all.
"""

from __future__ import annotations

import pytest

from .conftest import ROOT_TENANT_ID

pytestmark = pytest.mark.asyncio


def _service():
    from bisheng.app_runtime.domain.services.app_query_service import AppQueryService

    return AppQueryService


def _entries():
    from bisheng.app_runtime.domain.services import app_query_service

    return app_query_service


async def test_the_owner_reads_the_instance_through_the_credential_door(
    app_db, app_factory, app_owner, fake_orchestrator
):
    app, _ = await app_factory()
    payload = await _service().get_instance(app.id, actor=app_owner.payload, entry=_entries().LOG_ENTRY_MCP)
    assert payload["instance_id"] == "inst-1"


async def test_the_detail_page_and_the_credential_door_agree_for_the_owner(
    app_db, app_factory, app_owner, fake_orchestrator
):
    """AC-18: the same content, only the admission rule differs."""

    app, _ = await app_factory()
    through_page = await _service().get_instance(app.id, actor=app_owner.payload, entry=_entries().LOG_ENTRY_DETAIL)
    through_key = await _service().get_instance(app.id, actor=app_owner.payload, entry=_entries().LOG_ENTRY_MCP)
    assert through_page == through_key


async def test_a_tenant_administrator_reads_it_on_the_page_but_not_through_a_key(
    app_db, app_factory, app_owner, fake_orchestrator, monkeypatch, tenant_admin_payload
):
    from bisheng.common.errcode.app_factory import AppNotFoundError

    async def _is_tenant_admin(user_id: int, tenant_id: int) -> bool:
        return user_id == tenant_admin_payload.user_id

    monkeypatch.setattr(_entries(), "check_tenant_admin", _is_tenant_admin)
    app, _ = await app_factory()

    on_the_page = await _service().get_instance(app.id, actor=tenant_admin_payload, entry=_entries().LOG_ENTRY_DETAIL)
    assert on_the_page["instance_id"] == "inst-1"

    for entry in (_entries().LOG_ENTRY_CLI, _entries().LOG_ENTRY_MCP):
        with pytest.raises(AppNotFoundError):
            await _service().get_instance(app.id, actor=tenant_admin_payload, entry=entry)


async def test_a_super_admin_key_gets_no_bypass_either(app_db, app_factory, app_owner, fake_orchestrator):
    """``is_global_super`` is not consulted on a credential door, even to widen the tenant."""

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode.app_factory import AppNotFoundError

    app, _ = await app_factory()
    superuser = UserPayload(
        user_id=999_999, user_name="root", user_role=[], tenant_id=ROOT_TENANT_ID, is_global_super=True
    )

    with pytest.raises(AppNotFoundError):
        await _service().get_instance(app.id, actor=superuser, entry=_entries().LOG_ENTRY_MCP)


async def test_a_stranger_gets_the_same_answer_as_a_missing_application(
    app_db, app_factory, fake_orchestrator, normal_user
):
    """Existence must not be probeable by comparing two refusals."""

    from bisheng.common.errcode.app_factory import AppNotFoundError

    app, _ = await app_factory()

    with pytest.raises(AppNotFoundError) as stranger:
        await _service().get_instance(app.id, actor=normal_user.payload, entry=_entries().LOG_ENTRY_MCP)
    with pytest.raises(AppNotFoundError) as missing:
        await _service().get_instance("no-such-app", actor=normal_user.payload, entry=_entries().LOG_ENTRY_MCP)

    assert stranger.value.Code == missing.value.Code
    assert "owner" not in str(stranger.value.kwargs)


async def test_the_default_entry_keeps_the_detail_page_behaviour(
    app_db, app_factory, app_owner, fake_orchestrator, monkeypatch, tenant_admin_payload
):
    """No ``entry`` means the platform face — F054's existing callers are untouched."""

    async def _is_tenant_admin(user_id: int, tenant_id: int) -> bool:
        return user_id == tenant_admin_payload.user_id

    monkeypatch.setattr(_entries(), "check_tenant_admin", _is_tenant_admin)
    app, _ = await app_factory()

    payload = await _service().get_instance(app.id, actor=tenant_admin_payload)
    assert payload["instance_id"] == "inst-1"
