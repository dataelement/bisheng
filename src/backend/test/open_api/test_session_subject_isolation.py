import pytest
from fastapi import HTTPException

from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.database.models.session import MessageSession
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.services.session_subject_service import session_subject_from_principal


def principal(
    *,
    actor_kind: str = "service_account",
    actor_id: int = 7,
    tenant_id: int = 3,
    mode: str = "S",
    owner_id: int | None = 11,
    effective_user_id: int | None = None,
    end_user_id: str | None = None,
) -> OpenApiPrincipal:
    authorization_subject_type = (
        "service_account" if actor_kind == "service_account" and mode == "S" else "user"
    )
    authorization_subject_id = (
        actor_id if authorization_subject_type == "service_account" else effective_user_id
    )
    return OpenApiPrincipal(
        credential_id=23,
        actor_kind=actor_kind,
        actor_id=actor_id,
        actor_name="caller",
        tenant_id=tenant_id,
        resource_owner_user_id=owner_id,
        scopes=frozenset({"chat:invoke"}),
        mode=mode,
        authorization_subject_type=authorization_subject_type,
        authorization_subject_id=authorization_subject_id,
        effective_user_id=effective_user_id,
        end_user_id=end_user_id,
    )


def new_session(*, tenant_id: int = 3, user_id: int = 11) -> MessageSession:
    return MessageSession(
        chat_id="chat-1",
        flow_id="flow-1",
        flow_type=15,
        user_id=user_id,
        tenant_id=tenant_id,
    )


def test_sa_self_mode_stamps_compatibility_owner_and_typed_subject():
    subject = session_subject_from_principal(principal(end_user_id="customer-1"))
    row = subject.stamp(new_session(user_id=999))

    assert row.user_id == 11
    assert row.api_subject_type == "service_account"
    assert row.api_subject_id == 7
    assert row.external_user_id == "customer-1"
    assert subject.matches(row)


def test_sa_sessions_are_isolated_by_tenant_account_and_end_user():
    row = session_subject_from_principal(principal(end_user_id="customer-1")).stamp(new_session())

    assert not session_subject_from_principal(principal(actor_id=8, end_user_id="customer-1")).matches(row)
    assert not session_subject_from_principal(principal(tenant_id=4, end_user_id="customer-1")).matches(row)
    assert not session_subject_from_principal(principal(end_user_id="customer-2")).matches(row)
    assert not session_subject_from_principal(principal(end_user_id=None)).matches(row)


def test_sa_without_end_user_is_isolated_at_service_account_granularity():
    subject = session_subject_from_principal(principal(end_user_id=None))
    row = subject.stamp(new_session())

    assert row.external_user_id is None
    assert subject.matches(row)
    assert session_subject_from_principal(principal(end_user_id=None)).matches(row)


@pytest.mark.parametrize("actor_kind", ["service_account", "natural_person"])
def test_delegate_and_pat_sessions_remain_natural_person_sessions(actor_kind):
    subject = session_subject_from_principal(
        principal(
            actor_kind=actor_kind,
            actor_id=7 if actor_kind == "service_account" else 21,
            mode="D" if actor_kind == "service_account" else "S",
            owner_id=21,
            effective_user_id=21,
        )
    )
    row = subject.stamp(new_session(user_id=999))

    assert row.user_id == 21
    assert row.api_subject_type is None
    assert row.api_subject_id is None
    assert SessionSubject.natural_person(tenant_id=3, user_id=21).matches(row)


def test_public_v3_session_binds_source_tenant_and_resource():
    subject = SessionSubject.public_v3(
        tenant_id=3,
        operator_user_id=42,
        resource_id="published-flow",
    )
    row = subject.stamp(new_session())

    assert row.user_id == 42
    assert row.api_subject_type == "public_v3"
    assert row.flow_id == "published-flow"
    assert subject.matches(row)
    assert not SessionSubject.public_v3(
        tenant_id=3,
        operator_user_id=42,
        resource_id="other-flow",
    ).matches(row)


async def test_info_and_continuation_use_same_subject_matcher(monkeypatch):
    row = session_subject_from_principal(principal(end_user_id="customer-1")).stamp(new_session())

    async def get_one(_chat_id):
        return row

    monkeypatch.setattr(
        "bisheng.chat_session.domain.chat.MessageSessionDao.async_get_one",
        get_one,
    )
    own = session_subject_from_principal(principal(end_user_id="customer-1"))
    assert await ChatSessionService.get_subject_session("chat-1", own) is row

    other = session_subject_from_principal(principal(end_user_id="customer-2"))
    with pytest.raises(HTTPException) as exc:
        await ChatSessionService.get_subject_session("chat-1", other)
    assert exc.value.status_code == 404


async def test_missing_and_cross_subject_both_return_404(monkeypatch):
    foreign = session_subject_from_principal(principal(end_user_id="customer-1")).stamp(new_session())
    values = iter([None, foreign])

    async def get_one(_chat_id):
        return next(values)

    monkeypatch.setattr(
        "bisheng.chat_session.domain.chat.MessageSessionDao.async_get_one",
        get_one,
    )
    subject = SessionSubject.natural_person(tenant_id=3, user_id=21)
    for chat_id in ("missing", "foreign"):
        with pytest.raises(HTTPException) as exc:
            await ChatSessionService.get_subject_session(chat_id, subject)
        assert exc.value.status_code == 404
