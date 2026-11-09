"""Execution retains the original registered Owner receipts in the same TX."""

import pytest

from bisheng.permission.application.identity import resolve_permission_actor
from test.knowledge_unification import test_model_delete_plan_application as actual

model_owner_tenant = actual.model_owner_tenant
removal_session = actual.removal_session
impact = actual.impact
ready = actual.ready


async def test_private_execution_prepare_uses_the_actual_core_and_registered_owner_receipts(ready):
    session, references, _ = ready
    with actual.native.actor() as identity:
        actual.web(identity)
        prepared = await references._aprepare_removed_models(
            session, identity=identity, server_id=1, retained_model_ids=(), delete_server=True
        )
        references.runtime.verifier.validate_owner_receipts(session, prepared.receipts)
        assert prepared.inspection.check_complete and prepared.inspection.blocked
        assert tuple(receipt.target.key for receipt in prepared.receipts) == prepared.inspection.targets
        assert len(prepared.receipts) == 5
        count = await references.runtime.aprepare_target_deletion(
            session, receipts=prepared.receipts, operation_id="same-native-operation",
            operation_type="model_delete_server", actor=await resolve_permission_actor(identity),
        )
        assert count == 5


async def test_empty_owned_provider_preparation_does_not_mint_model_receipts(ready):
    session, references, _ = ready
    with actual.native.actor() as identity:
        actual.web(identity)
        prepared = await references._aprepare_removed_models(
            session, identity=identity, server_id=5, retained_model_ids=(), delete_server=True
        )
    assert prepared.receipts == () and not prepared.inspection.targets
