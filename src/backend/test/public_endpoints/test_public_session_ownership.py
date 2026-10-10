import pytest

from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.database.models.session import MessageSession


def _session(**updates) -> MessageSession:
    values = {
        "chat_id": "chat-1",
        "flow_id": "flow-1",
        "flow_name": "Published",
        "flow_type": 10,
        "user_id": 8,
        "tenant_id": 3,
        "api_subject_type": "public_v3",
        "api_subject_id": None,
        "is_delete": False,
    }
    values.update(updates)
    return MessageSession(**values)


@pytest.mark.parametrize(
    "updates",
    [
        {"tenant_id": 4},
        {"flow_id": "flow-2"},
        {"api_subject_type": None},
        {"api_subject_type": "service_account", "api_subject_id": 8},
        {"is_delete": True},
    ],
)
def test_public_subject_rejects_cross_source_resource_and_tenant(updates) -> None:
    subject = SessionSubject.public_v3(tenant_id=3, operator_user_id=8, resource_id="flow-1")
    assert subject.matches(_session(**updates)) is False


def test_public_subject_matches_only_bound_public_session() -> None:
    subject = SessionSubject.public_v3(tenant_id=3, operator_user_id=8, resource_id="flow-1")
    assert subject.matches(_session()) is True
