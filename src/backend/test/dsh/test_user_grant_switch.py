"""Direct grant settings are independent; positive enabled sources govern access."""

from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session

from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.subject_policy import DshSubjectPolicyRepository
from bisheng.dsh.domain.schemas.contracts import DshUserPolicyInput
from bisheng.dsh.domain.schemas.model_policy import DshModelPolicyState, DshPolicySnapshot
from test.dsh.test_policy_service import service_factory, sql_store  # noqa: F401
from test.dsh.test_subject_policy import subject_store, update  # noqa: F401


@pytest.mark.parametrize("enabled,limit", [(True, 0), (False, 500), (True, 500)])
def test_input_preserves_independent_settings(enabled, limit):
    request = DshUserPolicyInput(operation_id="switch", expected_version=0, enabled=enabled, monthly_token_limit=limit)
    assert (request.enabled, request.monthly_token_limit) == (enabled, limit)


def test_zero_quota_is_excluded_from_model_listing_and_recovery():
    snapshot = DshPolicySnapshot(
        tenant_id=2,
        user_id=20,
        rows=[
            DshModelPolicyState(
                model_id=model,
                enabled=enabled,
                monthly_token_limit=limit,
                version=1,
                quota_epoch=1,
                quota_sync_state="READY",
                pending_operation_id=None,
            )
            for model, enabled, limit in [(7, 1, 0), (8, 0, 500), (9, 1, 300)]
        ],
    )
    assert snapshot.allowed_model_ids == [9]
    assert snapshot.recovery_payload()["model_configs"] == [{"model_id": 9, "monthly_token_limit": 300}]


@pytest.mark.parametrize(
    "enabled,limit,inherited,expected",
    [
        (True, 0, False, 0),
        (False, 500, False, 0),
        (True, 500, False, 500),
        (True, 0, True, 300),
        (False, 500, True, 300),
        (True, 500, True, 500),
    ],
)
def test_effective_permissions_use_positive_enabled_sources(subject_store, enabled, limit, inherited, expected):  # noqa: F811
    with Session(subject_store) as session, session.begin():
        repository = DshSubjectPolicyRepository(session)
        session.add(
            DshUserPolicy(
                user_id=20,
                tenant_id=2,
                model_id=7,
                enabled=int(enabled),
                monthly_token_limit=limit,
                version=1,
                quota_epoch=1,
                quota_sync_state="READY",
                updated_by=90,
            )
        )
        if inherited:
            update(repository, "DEPARTMENT", 10, 100)
            update(repository, "ROLE", 41, 300)
        session.flush()
        actual = repository.user_permissions([(20, "admin")], model_id=7, limit=10)["items"][0]
        assert (actual["direct_enabled"], actual["direct_monthly_token_limit"]) == (enabled, limit)
        assert actual["authorized"] == (expected > 0)
        assert actual["monthly_token_limit"] == expected
        effective = repository.effective(20)
        assert effective.allowed_model_ids == ([7] if expected > 0 else [])
        assert effective.monthly_token_limit == expected
        assert repository.entitled_user_ids() == ([20] if expected > 0 else [])


async def test_operation_persists_switch_and_quota_across_enable_disable(service_factory):  # noqa: F811
    service, _state, _quota = service_factory()
    service.validate_models = AsyncMock(return_value=True)
    for version, (enabled, limit) in enumerate([(True, 0), (False, 500), (True, 500)]):
        result = await service.update_policy(
            user_id=20,
            actor_user_id=90,
            model_id=7,
            request=DshUserPolicyInput(
                operation_id=f"switch-{version}",
                expected_version=version,
                enabled=enabled,
                monthly_token_limit=limit,
            ),
        )
        assert result["status"] == "SUCCEEDED"
        with service.repository_scope() as repository:
            saved = repository.get_model(20, 7)
            assert (bool(saved.enabled), saved.monthly_token_limit, saved.version) == (enabled, limit, version + 1)
