"""覆盖 AC: AC-06, AC-07, AC-08, AC-09, AC-11."""

import pytest

from test.dsh.test_subject_policy import subject_store, update  # noqa: F401


@pytest.mark.parametrize(
    "personal,enabled,expected", [(0, False, 100000), (0, True, 0), (6000, True, 6000), (1000000, True, 1000000)]
)
def test_personal_quota_override(subject_store, personal, enabled, expected):  # noqa: F811
    from sqlmodel import Session

    from bisheng.dsh.domain.models.user_policy import DshUserPolicy
    from bisheng.dsh.domain.repositories.subject_policy import DshSubjectPolicyRepository

    with Session(subject_store) as session, session.begin():
        repository = DshSubjectPolicyRepository(session)
        update(repository, "DEPARTMENT", 10, 100000)
        session.add(
            DshUserPolicy(
                user_id=20,
                tenant_id=2,
                model_id=7,
                enabled=int(enabled),
                monthly_token_limit=personal,
                version=1,
                quota_epoch=1,
                quota_sync_state="READY",
                updated_by=90,
            )
        )
        session.flush()
        assert repository.effective(20).rows[0].monthly_token_limit == expected
        from bisheng.dsh.domain.schemas.admin import ModelUserPermission

        permission = repository.user_permissions([(20, "admin")], model_id=7, limit=10)["items"][0]
        ModelUserPermission.model_validate(permission)
        assert (
            repository.user_permissions([(20, "admin")], model_id=7, limit=10)["items"][0]["monthly_token_limit"]
            == expected
        )

        if enabled:
            from sqlmodel import select

            direct = session.exec(select(DshUserPolicy).where(DshUserPolicy.user_id == 20)).one()
            direct.enabled = 0
            direct.monthly_token_limit = 0
            direct.version += 1
            session.flush()
            assert repository.effective(20).rows[0].monthly_token_limit == 100000
            restored = repository.user_permissions([(20, "admin")], model_id=7, limit=10)["items"][0]
            assert restored["monthly_token_limit"] == 100000
            assert restored["direct_enabled"] is False
            ModelUserPermission.model_validate(restored)


def test_unassigned_and_numeric_user_search(subject_store):  # noqa: F811
    from sqlmodel import Session

    from bisheng.user.domain.repositories.dsh_profile import UserDshProfileRepository

    with Session(subject_store) as session:
        assert UserDshProfileRepository.access_users(session, keyword="20") == [(20, "admin")]
        assert UserDshProfileRepository.access_users(session, unassigned_only=True) == [(21, "guest")]
