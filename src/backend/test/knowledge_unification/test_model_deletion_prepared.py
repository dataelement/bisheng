"""Execution retains the original registered Owner receipts in the same TX."""

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
        assert prepared.inspection.check_complete and prepared.inspection.blocked
        assert {target.target_id for target in prepared.inspection.targets} == {"11", "12", "13", "14", "15"}
        assert not hasattr(prepared, "receipts")


async def test_empty_owned_provider_preparation_does_not_mint_model_receipts(ready):
    session, references, _ = ready
    with actual.native.actor() as identity:
        actual.web(identity)
        prepared = await references._aprepare_removed_models(
            session, identity=identity, server_id=5, retained_model_ids=(), delete_server=True
        )
    assert not hasattr(prepared, "receipts") and not prepared.inspection.targets
