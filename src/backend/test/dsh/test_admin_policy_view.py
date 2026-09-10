"""AC-18/21/26/27/30: authoritative scoped management projection and rejection."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session

from bisheng.common.errcode.dsh import DshModelNotAllowedError
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.services.profile import profile_scope
from test.dsh.test_policy_repository import NOW, sql_store  # noqa: F401


def test_last_call_is_scoped_bounded_and_redacted(sql_store):  # noqa: F811
    from bisheng.dsh.domain.repositories.admin_queries import DshAdminQueryRepository

    with Session(sql_store) as session, session.begin():
        for tenant, user, name, minutes in [
            (2, 20, "older", 0),
            (2, 20, "latest", 1),
            (3, 20, "foreign", 2),
            (2, 21, "other", 3),
        ]:
            with profile_scope(tenant):
                session.add(
                    DshModelCall(
                        request_id=name,
                        user_id=user,
                        tenant_id=tenant,
                        model_id=4,
                        seat_id="seat",
                        session_id="session",
                        grant_version=1,
                        policy_version=1,
                        quota_epoch=1,
                        event_version=2,
                        usage_month="2026-09",
                        status="USAGE_UNKNOWN",
                        started_at=NOW + timedelta(minutes=minutes),
                        ended_at=NOW + timedelta(minutes=minutes, seconds=10),
                        provider_request_id="private-provider-reference",
                        trace_id="private-trace",
                        update_time=NOW,
                    )
                )
                session.flush()
    with Session(sql_store) as session, profile_scope(2):
        result = DshAdminQueryRepository(session).last_call(20)
        assert result["request_id"] == "latest" and result["total_tokens"] is None
        assert set(result) == {
            "request_id",
            "model_id",
            "status",
            "started_at",
            "finished_at",
            "total_tokens",
            "projected_at",
        }
        assert result["started_at"].endswith("Z") and result["projected_at"].endswith("Z")
        assert DshAdminQueryRepository(session).last_call(99) is None


async def test_candidates_use_configured_ids_and_target_tenant_governance():
    from bisheng.core.context.tenant import get_current_tenant_id
    from bisheng.dsh.admin_runtime import read_available_models

    async def snapshot(model_id):
        assert get_current_tenant_id() == 2
        if model_id == 6:
            raise DshModelNotAllowedError()
        return SimpleNamespace(
            id=model_id, tenant_id=1 if model_id == 5 else 2, name=f"Model {model_id}", model_name="qwen-max"
        ), SimpleNamespace(name=f"Provider {model_id}", type="openai")

    loader = AsyncMock(side_effect=snapshot)
    with profile_scope(2):
        result = await read_available_models({"4": object(), "5": object(), "6": object()}, loader)
    assert result == [
        {"id": 4, "name": "Provider 4 / qwen-max", "is_root_shared": False},
        {"id": 5, "name": "Provider 5 / qwen-max", "is_root_shared": True},
    ]
    assert [call.args[0] for call in loader.await_args_list] == [4, 5, 6]
    with profile_scope(2), pytest.raises(TimeoutError):
        await read_available_models({"4": object()}, AsyncMock(side_effect=TimeoutError()))


@pytest.mark.parametrize("unavailable", [False, True])
async def test_management_projection_preserves_policy_and_distinguishes_empty_from_unavailable(unavailable):
    from bisheng.dsh.admin_runtime import build_policy_view

    candidates = AsyncMock(side_effect=TimeoutError()) if unavailable else AsyncMock(return_value=[])
    latest = AsyncMock(side_effect=TimeoutError()) if unavailable else AsyncMock(return_value=None)
    view = build_policy_view(
        policy_reader=AsyncMock(return_value=None),
        live_reader=AsyncMock(),
        persisted_reader=AsyncMock(),
        billing_timezone="UTC",
        available_models_reader=candidates,
        last_call_reader=latest,
    )
    with profile_scope(2):
        result = await view(20)
    assert result["tenant_id"] == 2 and result["version"] == 0
    assert result["available_models"] == [] and result["last_call"] is None
    assert result["available_models_source"] == ("unavailable" if unavailable else "live")
    assert result["last_call_source"] == ("unavailable" if unavailable else "persisted")
    candidates.assert_awaited_once_with(20)
    latest.assert_awaited_once_with(20)
