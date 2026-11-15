"""Upgraded workbench models become visible to every member, once per tenant."""

from sqlmodel import Session, select

from bisheng.dsh.domain.models.subject_policy import DshSubjectPolicy
from bisheng.dsh.domain.models.unified_policy import ModelVisibility, UnifiedPolicyAudit
from bisheng.dsh.domain.repositories.unified_policy import UnifiedPolicyRepository
from bisheng.dsh.domain.schemas.unified_policy import ModelVisibilityInput, PolicySubject
from bisheng.dsh.domain.services.legacy_credit_migration import MIGRATION_RESOURCE
from bisheng.dsh.domain.services.workbench_visibility_backfill import (
    BACKFILL_RESOURCE,
    backfill_tenant_visibility,
    workbench_model_ids,
)
from test.dsh.test_subject_policy import subject_store as subject_store
from test.dsh.test_unified_policy_repository import store as store


def test_workbench_model_ids_parse_order_and_bad_values():
    value = '{"models": [{"id": "7"}, {"id": 8}, {"id": "7"}, {"id": ""}, {"name": "x"}, {"id": "abc"}]}'
    assert workbench_model_ids(value) == [7, 8]
    assert workbench_model_ids(None) == []
    assert workbench_model_ids("not json") == []
    assert workbench_model_ids('{"models": null}') == []


def test_upgraded_tenant_gets_everyone_once_and_admin_edits_stick(store):
    with Session(store) as session, session.begin():
        preview = backfill_tenant_visibility(session, [7, 8], apply=False)
        assert preview == {"tenant_id": 2, "state": "preview", "granted": [7, 8], "kept": []}
        assert session.exec(select(ModelVisibility)).first() is None
    with Session(store) as session, session.begin():
        applied = backfill_tenant_visibility(session, [7, 8], apply=True)
        assert applied["state"] == "applied" and applied["granted"] == [7, 8]
        repo = UnifiedPolicyRepository(session)
        assert repo.visibility(7)["everyone"] is True
        assert repo.effective(21).allowed_model_ids == [7, 8]
    # An admin narrows the model afterwards; a later startup must not reopen it.
    with Session(store) as session, session.begin():
        UnifiedPolicyRepository(session).save_visibility(7, 20, ModelVisibilityInput(version=1, everyone=False))
    with Session(store) as session, session.begin():
        assert backfill_tenant_visibility(session, [7, 9], apply=True)["state"] == "already_applied"
        assert UnifiedPolicyRepository(session).visibility(7)["everyone"] is False
        assert session.exec(select(ModelVisibility).where(ModelVisibility.model_id == 9)).first() is None
        markers = session.exec(select(UnifiedPolicyAudit).where(UnifiedPolicyAudit.resource == BACKFILL_RESOURCE)).all()
        assert len(markers) == 1


def test_tenant_already_using_visibility_is_skipped_unless_operator_includes_it(store):
    with Session(store) as session, session.begin():
        UnifiedPolicyRepository(session).save_visibility(
            8, 20, ModelVisibilityInput(version=0, subjects=[PolicySubject(kind="USER", id=20)])
        )
    with Session(store) as session, session.begin():
        assert backfill_tenant_visibility(session, [7, 8], apply=True)["state"] == "skipped_configured"
        assert (
            session.exec(select(UnifiedPolicyAudit).where(UnifiedPolicyAudit.resource == BACKFILL_RESOURCE)).first()
            is None
        )
    with Session(store) as session, session.begin():
        applied = backfill_tenant_visibility(session, [7, 8], apply=True, include_configured=True)
        assert (applied["granted"], applied["kept"]) == ([7], [8])
        repo = UnifiedPolicyRepository(session)
        assert repo.visibility(7)["everyone"] is True
        assert repo.visibility(8)["everyone"] is False


def test_tenant_with_unimported_legacy_grants_waits_for_credit_migration(store):
    with Session(store) as session, session.begin():
        session.add(
            DshSubjectPolicy(
                tenant_id=2,
                subject_type="DEPARTMENT",
                subject_id=10,
                model_id=7,
                enabled=1,
                monthly_token_limit=1,
                updated_by=20,
            )
        )
    with Session(store) as session, session.begin():
        assert backfill_tenant_visibility(session, [7], apply=True)["state"] == "skipped_legacy_grants"
        assert session.exec(select(UnifiedPolicyAudit)).first() is None
    with Session(store) as session, session.begin():
        UnifiedPolicyRepository(session)._audit(20, MIGRATION_RESOURCE, None, {"users": 1})
    with Session(store) as session, session.begin():
        assert backfill_tenant_visibility(session, [7], apply=True)["granted"] == [7]
