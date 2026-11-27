"""Super operators keep the selected model tenant without becoming its members."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlmodel import select

from bisheng.common.errcode.dsh import DshModelNotAllowedError, DshUserDisabledError
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.dsh.domain.models.admin_operation import DshAdminOperation
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage
from bisheng.dsh.domain.models.tool_call import DshToolCall
from bisheng.dsh.domain.models.unified_policy import CreditRule, ModelVisibility, PersonalLedgerState
from bisheng.dsh.domain.repositories.identities import CurrentIdentityRecords
from bisheng.dsh.domain.repositories.unified_policy import UnifiedPolicyRepository
from bisheng.dsh.domain.repositories.usage import DshUsageRepository
from bisheng.dsh.domain.schemas.pricing import CreditSettingState
from bisheng.dsh.domain.services import chat_credits, model_catalog, vision
from bisheng.llm.domain.models.llm_server import LLMDao, LLMModel, LLMServer
from bisheng.llm.domain.schemas import WorkbenchModelConfig
from bisheng.llm.domain.services.llm import LLMService
from bisheng.user.domain.models.user import User
from test.dsh.pricing_fixtures import LEGACY_EQUIVALENT_PRICING
from test.dsh.test_quota_admission import quota as quota
from test.fixtures.managed_tenant import managed_db as managed_db


@pytest.fixture
async def execution(managed_db, monkeypatch):
    from bisheng.core import database
    from bisheng.database.models import tenant as tenant_module
    from bisheng.dsh import runtime
    from bisheng.llm.domain.models import llm_server
    from bisheng.user.domain.models import user as user_module
    from bisheng.utils import http_middleware

    await managed_db.create(
        User,
        Tenant,
        UserTenant,
        LLMServer,
        LLMModel,
        ModelVisibility,
        CreditRule,
        PersonalLedgerState,
        DshModelCall,
        DshToolCall,
        DshMonthlyUsage,
        DshAdminOperation,
    )
    for module in (database, tenant_module, user_module, llm_server):
        monkeypatch.setattr(module, "get_sync_db_session", managed_db.sync_sessions)
        monkeypatch.setattr(module, "get_async_db_session", managed_db.sessions)
    state = SimpleNamespace(super=True, shared={902}, db=managed_db)

    async def qualify(user_id, *, force_refresh=False):
        assert user_id in (78, 79) and force_refresh
        return state.super and user_id == 78

    monkeypatch.setattr(http_middleware, "_check_is_global_super", qualify)
    with bypass_tenant_filter(), managed_db.sync_sessions() as session, session.begin():
        session.add(User(user_id=78, user_name="Root operator", password=str(uuid4())))
        session.add(User(user_id=79, user_name="Child member", password=str(uuid4())))
        session.add_all([Tenant(id=i, tenant_code=f"t{i}", tenant_name=f"T{i}") for i in (1, 2, 3)])
        session.add(UserTenant(id=1, tenant_id=1, user_id=78, is_active=1, status="active"))
        session.add(UserTenant(id=2, tenant_id=3, user_id=79, is_active=1, status="active"))
        for sid, tid in ((901, 3), (902, 1), (903, 2), (904, 1)):
            session.add(LLMServer(id=sid, tenant_id=tid, name=f"Provider {sid}", type="openai", config={}))
            session.add(
                LLMModel(id=sid, tenant_id=tid, server_id=sid, model_name="same-name", model_type="llm", online=True)
            )
        session.add(LLMModel(id=905, tenant_id=3, server_id=901, model_name="offline", model_type="llm", online=False))
        session.add(ModelVisibility(tenant_id=3, model_id=901, everyone=False, subjects=[], updated_by=78))
        session.add(PersonalLedgerState(tenant_id=3, user_id=78, quota_epoch=7))
        session.add(PersonalLedgerState(tenant_id=1, user_id=78, quota_epoch=99))

    async def shared(*args, **kwargs):
        return state.shared

    monkeypatch.setattr(LLMDao, "aget_shared_server_ids_for_leaf", shared)
    monkeypatch.setattr(model_catalog, "read_workbench_metadata", AsyncMock(return_value=WorkbenchModelConfig()))
    monkeypatch.setattr(vision, "read_catalog_vision", AsyncMock(return_value={901: False, 902: False}))
    monkeypatch.setattr(vision, "read_vision", AsyncMock(return_value=SimpleNamespace(vision=False)))
    state.admit = AsyncMock(side_effect=lambda event, **kwargs: event)
    state.settle = AsyncMock()
    state.service = SimpleNamespace(
        activate=AsyncMock(),
        model=SimpleNamespace(settle_usage=state.settle),
        usage=SimpleNamespace(check_and_start=state.admit),
    )
    monkeypatch.setattr(runtime, "get_model_runtime", AsyncMock(return_value=state.service))
    monkeypatch.setattr(runtime, "read_model_pricing", AsyncMock(return_value=LEGACY_EQUIVALENT_PRICING))
    monkeypatch.setattr(runtime, "read_credit_setting", AsyncMock(return_value=CreditSettingState()))
    monkeypatch.setattr(runtime, "read_policy", AsyncMock(side_effect=AssertionError("operator read a member policy")))
    return state


@pytest.mark.parametrize("dsh_enabled", [False, True])
async def test_chat_and_task_accept_the_child_catalog_before_creating_models(execution, monkeypatch, dsh_enabled):
    from bisheng.api.v1.schema.chat_schema import APIChatCompletion
    from bisheng.api.v1.schemas import WorkstationConfig
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.services.config_service import settings
    from bisheng.linsight.domain.services import agent_factory
    from bisheng.workstation.domain.services import chat_service, run_send

    monkeypatch.setitem(settings.__dict__, "dsh", settings.dsh.model_copy(update={"enabled": dsh_enabled}))
    monkeypatch.setattr(type(settings), "get_linsight_conf", lambda self: SimpleNamespace(default_temperature=0))
    # This is also the context a queued worker has: only the persisted tenant,
    # without an HTTP management marker or a copied administrator boolean.
    with tenant_execution_scope(3):
        assert [m.id for m in await model_catalog.user_workbench_models(78)] == ["901", "902"]
        user = UserPayload(user_id=78, user_name="operator", tenant_id=1, user_role=[], is_global_super=True)
        data = APIChatCompletion(clientTimestamp="t", model="901", text="hello")
        assert await run_send._model_display_name(data, user) == "same-name"
        monkeypatch.setattr(chat_service.WorkStationService, "aget_config", AsyncMock(return_value=WorkstationConfig()))
        conversation = SimpleNamespace(chat_id="child-chat")
        monkeypatch.setattr(chat_service.MessageSessionDao, "async_insert_one", AsyncMock())
        monkeypatch.setattr(chat_service.MessageSessionDao, "async_get_one", AsyncMock(return_value=conversation))
        monkeypatch.setattr(chat_service.ChatMessageDao, "ainsert_one", AsyncMock())
        monkeypatch.setattr(chat_service.telemetry_service, "log_event", AsyncMock())
        daily_factory = AsyncMock(return_value="child daily model")
        monkeypatch.setattr(LLMService, "get_bisheng_llm", daily_factory)
        initialized = await chat_service._agent_initialize_chat(data, user)
        assert initialized[3] == "child daily model" and initialized[4].id == "901"
        assert daily_factory.await_args.kwargs["model_id"] == "901"
        monkeypatch.setattr(LLMService, "get_workbench_llm_candidates", AsyncMock(return_value=WorkbenchModelConfig()))
        factory = AsyncMock(return_value="child model")
        monkeypatch.setattr(LLMService, "get_bisheng_linsight_llm", factory)
        result, _ = await agent_factory._resolve_model(SimpleNamespace(user_id=78, tenant_id=3), "901")
        assert result == "child model"
        for forbidden in ("903", "904", "905"):
            with pytest.raises(ValueError, match="not currently available"):
                await agent_factory._resolve_model(SimpleNamespace(user_id=78, tenant_id=3), forbidden)
        factory.assert_awaited_once()


async def test_admin_call_is_priced_and_settled_in_child_ledger(execution):
    model = SimpleNamespace(user_id=78, model_info=SimpleNamespace(id=901))
    with tenant_execution_scope(3):
        state = await chat_credits.start(model)
        _, event, usage = state
        assert (event.tenant_id, event.user_id, event.model_id, event.quota_epoch) == (3, 78, 901, 7)
        assert event.pricing is not None and not event.pricing.free
        assert execution.admit.await_args.kwargs == {"monthly_token_limit": 0, "mode": "unmetered"}
        chat_credits.observe(
            usage,
            ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content="answer",
                            usage_metadata={"input_tokens": 5, "output_tokens": 2, "total_tokens": 7},
                        )
                    )
                ]
            ),
        )
        await chat_credits.finish(state, True)
        execution.settle.assert_awaited_once()
        assert execution.settle.await_args.args[1].total_tokens == 7
        execution.admit.reset_mock()
        await chat_credits.start(model, mode="probe")
        execution.admit.assert_not_awaited()
        # Desktop authentication must still reject a fabricated child member.
        assert await CurrentIdentityRecords().get("3", "78") is None


async def test_child_member_keeps_personal_visibility_and_quota(execution, monkeypatch):
    from bisheng.common.errcode.dsh import DshMonthlyTokenLimitExceededError
    from bisheng.dsh import runtime
    from bisheng.dsh.infrastructure.quota_redis import QuotaRejected

    visible = AsyncMock(return_value={902})
    monkeypatch.setattr(model_catalog, "read_visible_model_ids", visible)
    monkeypatch.setattr(
        runtime,
        "read_policy",
        AsyncMock(
            return_value=SimpleNamespace(
                allowed_model_ids=[902],
                version=1,
                quota_epoch=1,
                monthly_token_limit=0,
            )
        ),
    )
    with tenant_execution_scope(3):
        assert [model.id for model in await model_catalog.user_workbench_models(79)] == ["902"]
        visible.assert_awaited_once_with(79, [901, 902])
        with pytest.raises(DshModelNotAllowedError):
            await chat_credits.start(SimpleNamespace(user_id=79, model_info=SimpleNamespace(id=901)))
        execution.admit.assert_not_awaited()
        execution.admit.side_effect = QuotaRejected("quota_exceeded")
        with pytest.raises(DshMonthlyTokenLimitExceededError):
            await chat_credits.start(SimpleNamespace(user_id=79, model_info=SimpleNamespace(id=902)))
        assert execution.admit.await_args.kwargs == {"monthly_token_limit": 0, "mode": ""}


@pytest.mark.parametrize("model_id", [903, 904, 905])
async def test_admin_call_still_rejects_sibling_unshared_and_offline_models(execution, model_id):
    with tenant_execution_scope(3), pytest.raises(DshModelNotAllowedError):
        await chat_credits.start(SimpleNamespace(user_id=78, model_info=SimpleNamespace(id=model_id)))
    execution.admit.assert_not_awaited()


@pytest.mark.parametrize("change", ["revoked", "disabled_user", "disabled_tenant", "disabled_home"])
async def test_stale_operator_or_inactive_identity_cannot_start_a_call(execution, change):
    if change == "revoked":
        execution.super = False
    else:
        with bypass_tenant_filter(), execution.db.sync_sessions() as session, session.begin():
            if change == "disabled_user":
                session.get(User, 78).delete = 1
            else:
                session.get(Tenant, 1 if change == "disabled_home" else 3).status = "disabled"
    with tenant_execution_scope(3):
        with pytest.raises(DshUserDisabledError):
            await model_catalog.user_workbench_models(78)
        with pytest.raises(DshUserDisabledError):
            await chat_credits.start(SimpleNamespace(user_id=78, model_info=SimpleNamespace(id=901)))
    execution.admit.assert_not_awaited()


async def test_root_provider_share_is_checked_again_at_invocation(execution):
    with tenant_execution_scope(3):
        assert "902" in {model.id for model in await model_catalog.user_workbench_models(78)}
        execution.shared.clear()
        with pytest.raises(DshModelNotAllowedError):
            await chat_credits.start(SimpleNamespace(user_id=78, model_info=SimpleNamespace(id=902)))
    execution.admit.assert_not_awaited()


async def test_unverifiable_operator_authority_fails_before_model_admission(execution, monkeypatch):
    from bisheng.common.errcode.admin_scope import AdminScopeUnavailableError
    from bisheng.utils import http_middleware

    monkeypatch.setattr(http_middleware, "_check_is_global_super", AsyncMock(side_effect=AdminScopeUnavailableError()))
    with tenant_execution_scope(3):
        with pytest.raises(AdminScopeUnavailableError):
            await model_catalog.user_workbench_models(78)
        with pytest.raises(AdminScopeUnavailableError):
            await chat_credits.start(SimpleNamespace(user_id=78, model_info=SimpleNamespace(id=901)))
    execution.admit.assert_not_awaited()


async def test_operator_ledger_recovery_never_grants_foreign_personal_access(execution):
    with tenant_execution_scope(3), execution.db.sync_sessions() as session, session.begin():
        repo = DshUsageRepository(session)
        events, policy = repo.recovery_snapshot(78, billing_timezone="UTC")
        assert events == [] and policy["model_configs"] == []
        assert policy["shared_token_limit"] == 0 and policy["quota_epoch"] == 7
        repo.complete_recovery(78, expected_policy=policy, epoch=8)
        assert UnifiedPolicyRepository(session).ledger_policy(78).quota_epoch == 8
        rows = session.exec(select(PersonalLedgerState)).all()
        assert [(r.tenant_id, r.quota_epoch) for r in rows] == [(3, 8)]


async def test_real_redis_first_admin_call_and_recovery_preserve_accounting(execution, quota):
    from contextlib import contextmanager
    from datetime import UTC, datetime

    from bisheng.dsh.domain.services.automatic_quota_recovery import AutomaticQuotaRecovery
    from bisheng.dsh.domain.services.model import DshModelService
    from bisheng.dsh.domain.services.usage import DshUsageService

    @contextmanager
    def repository_scope(repository_type):
        with execution.db.sync_sessions() as session, session.begin():
            yield repository_type(session)

    quota.topology.automatic = True
    quota.recovery = AutomaticQuotaRecovery(quota, repository_scope, billing_timezone="UTC")
    usage = DshUsageService(quota)
    execution.service.usage = usage
    execution.service.model = DshModelService(
        policy_reader=None,
        model_loader=None,
        llm_builder=None,
        capabilities_for=None,
        usage=usage,
        now=lambda: datetime.now(UTC),
    )
    with tenant_execution_scope(3):
        state = await chat_credits.start(SimpleNamespace(user_id=78, model_info=SimpleNamespace(id=901)))
        event = state[1]
        state[2].usage = state[2].usage.model_copy(update={"input_tokens": 5, "output_tokens": 2, "total_tokens": 7})
        await chat_credits.finish(state, True)
        before = await quota.read_usage(3, 78, event.usage_month)
        assert before["used"] > 0
        # Delete only this test operator's gate; recovery must keep its usage,
        # even though no target-tenant member or selectable grant exists.
        await quota.redis.delete(quota.keys(event)[0])
        after = await quota.read_usage(3, 78, event.usage_month)
        assert after["used"] == before["used"]
