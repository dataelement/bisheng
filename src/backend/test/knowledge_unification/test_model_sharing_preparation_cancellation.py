"""Explicit maintenance cancellation validates an orphaned, unstarted preparation."""

from copy import deepcopy
from datetime import timedelta

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError
from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.core.context.tenant import management_tenant_scope
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.llm.application.model_deletion_context import model_deletion_request
from bisheng.llm.domain.models.model_sharing_intent import ModelSharingInitialization
from bisheng.permission.application.identity import resolve_permission_actor
from test.knowledge_unification import test_model_delete_plan_application as actual
from test.knowledge_unification import test_model_deletion_application as native_business
from test.knowledge_unification.test_model_provider_sharing_writers import install_sharing
from test.knowledge_unification.test_model_sharing_projection import reserved

business = native_business.business
impact = actual.impact
model_owner_tenant = actual.model_owner_tenant
ready = actual.ready
removal_session = actual.removal_session


async def interrupt(share, user, monkeypatch):
    # A killed process cannot run the new automatic exception cleanup. Keep a
    # real, committed orphan for the explicit maintenance-cancellation tests.
    await reserved(share.session_factory, share.references, share.plans, user)


async def saved(factory):
    async with factory() as session:
        return (await session.execute(sa.select(KnowledgeOperationPlan))).scalars().one()


async def test_cancellation_preserves_original_signed_payload_and_allows_new_command(business, monkeypatch):
    factory, _, _, _, client = business
    share = await install_sharing(business, monkeypatch)
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        await interrupt(share, user, monkeypatch)
        original = await saved(factory)
        preview = await share.aprepare_cancellation(identity=user, server_id=2)
        assert (await saved(factory)).model_execution_state == "PREPARING"
        result = await share.aprepare_cancellation(
            identity=user,
            server_id=2,
            expected_fingerprint=preview["fingerprint"],
        )
        assert result["abandoned"] is True
        after = await saved(factory)
        for key in (
            "actor_reference",
            "parameters",
            "request_hash",
            "plan_digest",
            "operation_id",
            "expires_at",
            "target_revisions",
        ):
            assert getattr(after, key) == getattr(original, key)
        assert after.model_execution_state == "ABANDONED" and not client.writes
        assert after.model_execution_metadata["ack"]["cancel_actor_user_id"] == user.user_id
        with pytest.raises(KnowledgeOperationPlanChangedError):
            share.providers.validate(after)
        await share.aset_sharing(identity=user, server_id=2, enabled=True)
        assert client.rows == {
            ("tenant:101", "shared_with", "llm_server:2"),
            ("tenant:202", "shared_with", "llm_server:2"),
        }


async def test_lost_expiry_signature_can_retire_but_is_never_resigned(business, monkeypatch):
    factory, _, _, _, _ = business
    share = await install_sharing(business, monkeypatch)
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        await interrupt(share, user, monkeypatch)
        async with factory() as session:
            async with session.begin():
                row = (await session.execute(sa.select(KnowledgeOperationPlan))).scalars().one()
                row.expires_at += timedelta(seconds=1)
                original_digest = row.plan_digest
        preview = await share.aprepare_cancellation(identity=user, server_id=2)
        await share.aprepare_cancellation(identity=user, server_id=2, expected_fingerprint=preview["fingerprint"])
        assert (await saved(factory)).plan_digest == original_digest


@pytest.mark.parametrize("mutation", ["payload", "fingerprint", "receipt", "frozen"])
async def test_changed_or_partly_prepared_record_cannot_cancel(business, monkeypatch, mutation):
    factory, _, _, _, client = business
    share = await install_sharing(business, monkeypatch)
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        await interrupt(share, user, monkeypatch)
        preview = await share.aprepare_cancellation(identity=user, server_id=2)
        async with factory() as session:
            async with session.begin():
                row = (await session.execute(sa.select(KnowledgeOperationPlan))).scalars().one()
                if mutation == "payload":
                    row.parameters = {"command_digest": "a" * 64}
                elif mutation == "fingerprint":
                    row.update_time += timedelta(seconds=1)
                elif mutation == "receipt":
                    session.add(
                        ModelSharingInitialization(plan_id=row.id, tenant_id=1, server_id=2, child_ids=[], model_ids=[])
                    )
                else:
                    metadata = deepcopy(row.model_execution_metadata)
                    metadata["sharing"] = {"before": [], "after": []}
                    row.model_execution_metadata = metadata
        with pytest.raises(KnowledgeOperationPlanChangedError):
            await share.aprepare_cancellation(identity=user, server_id=2, expected_fingerprint=preview["fingerprint"])
        assert not client.writes and (await saved(factory)).model_execution_state == "PREPARING"


@pytest.mark.parametrize("late", [False, True])
async def test_journal_before_cancel_blocks_and_late_journal_cannot_execute(business, monkeypatch, late):
    factory, _, _, _, client = business
    share = await install_sharing(business, monkeypatch)
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        await interrupt(share, user, monkeypatch)
        row = await saved(factory)
        preview = await share.aprepare_cancellation(identity=user, server_id=2)
        async with model_deletion_request(user, references=share.references, plans=share.plans) as request:
            native = await share._permission(request)
            before = await native.aread(server_id=2)
            if late:
                await share.aprepare_cancellation(
                    identity=user, server_id=2, expected_fingerprint=preview["fingerprint"]
                )
            prepared = await native.aprepare(
                before=before,
                after=(101,),
                confirmation_id=row.id,
                actor=await resolve_permission_actor(user),
                tenant_id=1,
                operation="model_share_server",
            )
            if late:
                with pytest.raises((PermissionPublishNotReadyError, KnowledgeOperationPlanChangedError)):
                    await native.aexecute(prepared)
                async with factory() as session:
                    async with session.begin():
                        current = await share.providers.aread_plan(session, confirmation_id=row.id)
                        with pytest.raises(KnowledgeOperationPlanChangedError):
                            await share.providers.abind(
                                session, current, server_id=2, metadata=row.model_execution_metadata
                            )
            else:
                with pytest.raises(PermissionPublishNotReadyError):
                    await share.aprepare_cancellation(
                        identity=user, server_id=2, expected_fingerprint=preview["fingerprint"]
                    )
        assert not client.writes
