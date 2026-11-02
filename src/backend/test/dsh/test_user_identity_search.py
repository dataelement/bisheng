"""Execute DSH identity search with tenant, department and cursor boundaries."""

import pytest
from sqlmodel import Session

from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.user.domain.models.user import User
from bisheng.user.domain.repositories.dsh_profile import UserDshProfileRepository
from test.dsh.test_model_access import model_access_db  # noqa: F401


@pytest.fixture
def identity_store(model_access_db):  # noqa: F811
    with Session(model_access_db) as session, session.begin():
        for user_id in range(20, 27):
            user = session.get(User, user_id)
            user.source = f"test-{user_id}"
            user.external_id = {
                20: "EMP_001%",
                21: "EMP_002",
                26: "EMPX001-other",
            }.get(user_id, "EMP_001%")
            session.add(user)
    return model_access_db


@pytest.mark.parametrize(
    "keyword, expected",
    [
        ("EMP_001%", [20]),
        ("EMP_00", [20, 21]),
        (" \u3000EMP_001%\n", [20]),
        ("emp_001%", []),
        ("001%", []),
        ("first-login", [20]),
        ("20", [20]),
        ("%", [26]),
        ("missing-user", []),
    ],
)
def test_identity_and_name_matches(identity_store, keyword, expected):
    with Session(identity_store) as session, profile_scope(2):
        rows = UserDshProfileRepository.access_users(session, keyword=keyword)
        assert [user_id for user_id, _ in rows] == expected


def test_identity_search_preserves_scope_and_cursor(identity_store):
    with Session(identity_store) as session, profile_scope(2):
        search = UserDshProfileRepository.access_users
        assert search(session, keyword="EMP_00", department_ids=[31]) == [(20, "e2e-dsh-first-login")]
        assert search(session, keyword="EMP_00", department_ids=[]) == []
        assert search(session, keyword="EMP_00", unassigned_only=True) == [(21, "e2e-dsh-existing")]
        assert search(session, keyword="EMP_00", user_ids=[21]) == [(21, "e2e-dsh-existing")]
        first = search(session, keyword="EMP_00", limit=1)
        assert [row[0] for row in first] == [20, 21]
        assert search(session, keyword="EMP_00", limit=1, after_user_id=first[0][0]) == [first[1]]
    with Session(identity_store) as session, profile_scope(3):
        assert search(session, keyword="EMP_001%") == [(22, "foreign")]
