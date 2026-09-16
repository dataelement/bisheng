"""F051 T010: callable range and audit subject, and the order they are decided in.

The order is load-bearing. A caller that sent a header it should not have must
be told about the header even when the model name is also wrong, or an agent's
correction loop gets a different answer on each attempt.
"""

import pytest

from bisheng.common.errcode.model_face import (
    ModelFaceAccessTokenRefusedError,
    ModelFaceCatalogUnavailableError,
    ModelFaceIdentityHeaderRefusedError,
)
from bisheng.open_api.domain.services import model_range_policy
from bisheng.open_api.domain.services.model_range_policy import (
    ACCESS_TOKEN_HEADER,
    END_USER_HEADER,
    SUBJECT_KIND_APP_SELF,
    SUBJECT_KIND_USER,
    AccessSubject,
    register_access_subject_verifier,
    register_hosted_app_declaration_port,
    resolve_range_and_subject,
)
from test.open_api.model_gateway_fixtures import hosted_app_principal, service_account_principal


@pytest.fixture(autouse=True)
def _restore_ports():
    declaration = model_range_policy.get_hosted_app_declaration_port()
    verifier = model_range_policy.get_access_subject_verifier()
    yield
    register_hosted_app_declaration_port(declaration)
    register_access_subject_verifier(verifier)


class FakeDeclarationPort:
    def __init__(self, declared):
        self.declared = declared
        self.calls = []

    async def declared_model_names(self, app_id, tenant_id):
        self.calls.append((app_id, tenant_id))
        return self.declared


class FakeVerifier:
    def __init__(self, subject):
        self.subject = subject
        self.calls = []

    def verify(self, token, *, app_id, tenant_id):
        self.calls.append((token, app_id, tenant_id))
        return self.subject


async def test_service_account_gets_the_tenant_range_and_is_its_own_subject():
    principal = service_account_principal()

    model_range, subject = await resolve_range_and_subject(principal, {})

    assert model_range.kind == "tenant"
    assert (subject.subject_kind, subject.subject_id) == ("service_account", 31)
    assert subject.app_id is None


async def test_service_account_presenting_an_access_token_is_refused():
    principal = service_account_principal()

    with pytest.raises(ModelFaceAccessTokenRefusedError) as excinfo:
        await resolve_range_and_subject(principal, {ACCESS_TOKEN_HEADER: "anything at all"})

    assert excinfo.value.code == 26204


@pytest.mark.parametrize("principal_factory", [service_account_principal, hosted_app_principal])
async def test_a_well_formed_end_user_header_is_refused_for_every_actor(principal_factory):
    # The shared /api/v2 base validates this header's *format* and then adopts
    # a valid value silently. This face refuses it outright, which is why the
    # refusal has to live here.
    port = FakeDeclarationPort(frozenset({"gpt-4o"}))
    register_hosted_app_declaration_port(port)

    with pytest.raises(ModelFaceIdentityHeaderRefusedError) as excinfo:
        await resolve_range_and_subject(principal_factory(), {END_USER_HEADER: "external-1"})

    assert excinfo.value.code == 26205
    assert port.calls == []


async def test_identity_header_is_judged_before_the_access_token():
    register_hosted_app_declaration_port(FakeDeclarationPort(frozenset()))
    register_access_subject_verifier(FakeVerifier(None))

    with pytest.raises(ModelFaceIdentityHeaderRefusedError):
        await resolve_range_and_subject(
            hosted_app_principal(),
            {END_USER_HEADER: "external-1", ACCESS_TOKEN_HEADER: "expired"},
        )


async def test_a_forged_token_is_refused_even_when_the_declaration_is_unreadable():
    class BrokenPort:
        async def declared_model_names(self, app_id, tenant_id):
            raise RuntimeError("deployment row unreadable")

    register_hosted_app_declaration_port(BrokenPort())
    register_access_subject_verifier(FakeVerifier(None))

    with pytest.raises(ModelFaceAccessTokenRefusedError) as excinfo:
        await resolve_range_and_subject(hosted_app_principal(), {ACCESS_TOKEN_HEADER: "forged"})

    # Step 2 before step 3: answering 26216 ("cannot tell right now, retry")
    # to a permanently invalid token sends the caller round a loop that can
    # never succeed.
    assert excinfo.value.code == 26204


async def test_header_lookup_is_case_insensitive():
    with pytest.raises(ModelFaceIdentityHeaderRefusedError):
        await resolve_range_and_subject(service_account_principal(), {"x-end-user": "external-1"})


async def test_natural_person_also_gets_the_tenant_range():
    principal = service_account_principal().model_copy(update={"actor_kind": "natural_person", "effective_user_id": 12})

    model_range, subject = await resolve_range_and_subject(principal, {})

    assert model_range.kind == "tenant"
    assert subject.subject_kind == "natural_person"


async def test_hosted_app_without_a_registered_declaration_port_is_refused():
    with pytest.raises(ModelFaceCatalogUnavailableError) as excinfo:
        await resolve_range_and_subject(hosted_app_principal(), {})

    assert excinfo.value.code == 26216


async def test_hosted_app_declaration_port_failure_is_refused_not_widened():
    class BrokenPort:
        async def declared_model_names(self, app_id, tenant_id):
            raise RuntimeError("deployment row unreadable")

    register_hosted_app_declaration_port(BrokenPort())

    with pytest.raises(ModelFaceCatalogUnavailableError):
        await resolve_range_and_subject(hosted_app_principal(), {})


async def test_hosted_app_range_is_its_declaration_and_subject_defaults_to_the_app():
    register_hosted_app_declaration_port(FakeDeclarationPort(frozenset({"gpt-4o"})))

    model_range, subject = await resolve_range_and_subject(hosted_app_principal(), {})

    assert model_range.kind == "declared"
    assert model_range.declared == frozenset({"gpt-4o"})
    assert (subject.subject_kind, subject.subject_id) == (SUBJECT_KIND_APP_SELF, None)
    assert subject.app_id == "survey-app"


async def test_a_valid_access_token_names_the_visiting_user():
    register_hosted_app_declaration_port(FakeDeclarationPort(frozenset({"gpt-4o"})))
    verifier = FakeVerifier(AccessSubject(user_id=77))
    register_access_subject_verifier(verifier)

    model_range, subject = await resolve_range_and_subject(
        hosted_app_principal(), {ACCESS_TOKEN_HEADER: "signed-token"}
    )

    assert (subject.subject_kind, subject.subject_id) == (SUBJECT_KIND_USER, 77)
    # Attribution never widens or narrows what the application may call.
    assert model_range.declared == frozenset({"gpt-4o"})
    assert verifier.calls == [("signed-token", "survey-app", 9)]


async def test_an_invalid_access_token_is_refused_rather_than_downgraded():
    register_hosted_app_declaration_port(FakeDeclarationPort(frozenset({"gpt-4o"})))
    register_access_subject_verifier(FakeVerifier(None))

    with pytest.raises(ModelFaceAccessTokenRefusedError) as excinfo:
        await resolve_range_and_subject(hosted_app_principal(), {ACCESS_TOKEN_HEADER: "forged"})

    # Silently recording it as "the app itself" would make audit attribution
    # something a caller can steer by sending a broken token.
    assert excinfo.value.code == 26204


async def test_registration_replaces_the_default_port():
    register_hosted_app_declaration_port(FakeDeclarationPort(frozenset()))

    model_range, _subject = await resolve_range_and_subject(hosted_app_principal(), {})

    assert model_range.declared == frozenset()
