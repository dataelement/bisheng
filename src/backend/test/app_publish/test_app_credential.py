"""T055 — the hosted application's runtime credential (AC-57 … AC-60).

Every test here goes through the **real** ``validate_bearer`` rather than
calling the resolver directly. That is deliberate: the interesting failures of
this feature all live in the layers around the resolver — the prefix pin, the
subject registry lookup, the cache that must be evicted, the tenant gate — and a
test that calls ``resolve_hosted_app(row)`` proves none of them.

What each group is protecting:

* **AC-57** — issuance is re-issuance: the previous key is revoked *and* its
  cache entry evicted, so "the old container's token stops working" is true
  within the five-second bound rather than within a TTL nobody bounded.
* **AC-58** — offline is subject *deactivation*: the same plaintext must work
  again after a resume without a new publish. Deletion is the only terminal
  case, and it arrives through F054's hook.
* **AC-59** — the absence of a surface is asserted by reading the source tree,
  because "we did not build it" is otherwise untestable and stays untrue the
  first time somebody adds a convenience endpoint.
* **AC-60** — a disabled owner account must not take the application down, so
  nothing in the resolution path may read the ``user`` row.

The per-application surrogate (``hosted_app_subject``) gets its own test: two
applications of the same owner must revoke independently, which is the whole
reason that table exists instead of reusing ``owner_user_id`` as the subject.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from test.app_publish.conftest import ROOT_TENANT_ID, SUB_TENANT_ID


@pytest.fixture()
async def hosted_app_resolver():
    """Install the ``hosted_app`` resolver for the duration of one test.

    Registered through the composition root so the wiring under test is the one
    that ships, and torn down afterwards because ``SUBJECT_RESOLVERS`` and the
    deletion-hook list are both process-wide.
    """
    from bisheng.app_publish.composition import register
    from bisheng.app_runtime.domain.services import lifecycle_hooks
    from bisheng.open_api.domain.models.api_credential import SUBJECT_KIND_HOSTED_APP
    from bisheng.open_api.domain.services.credential_validator import SUBJECT_RESOLVERS

    lifecycle_hooks.clear_app_deleted_hooks()
    register()
    try:
        yield SUBJECT_RESOLVERS
    finally:
        SUBJECT_RESOLVERS.pop(SUBJECT_KIND_HOSTED_APP, None)
        lifecycle_hooks.clear_app_deleted_hooks()


async def _set_state(publish_db, app_id: str, state: str) -> None:
    """Move an application without going through ``AppStateService``.

    These tests are about the credential, not about the transition table, and
    the service needs a live orchestrator to reach ``online``.
    """
    from bisheng.database.models.app import AppDao

    async with publish_db() as session:
        app = await AppDao.aget(session, app_id)
        app.state = state
        session.add(app)
        await session.commit()


async def _live_credentials(subject_id: int):
    from bisheng.open_api.domain.models.api_credential import SUBJECT_KIND_HOSTED_APP
    from bisheng.open_api.domain.repositories.credential_repository import CredentialRepository

    rows = await CredentialRepository.list_by_subject(SUBJECT_KIND_HOSTED_APP, subject_id)
    return [row for row in rows if row.revoked_at is None]


async def _subject_id(app_id: str) -> int:
    from bisheng.app_publish.domain.models.hosted_app_subject import HostedAppSubjectDao
    from bisheng.core.database import get_async_db_session

    async with get_async_db_session() as session:
        row = await HostedAppSubjectDao.aget_by_app(session, app_id)
    return int(row.id)


# ---------------------------------------------------------------------------
# AC-57 — issue / re-issue
# ---------------------------------------------------------------------------


async def test_issued_plaintext_carries_the_hosted_app_prefix(publish_db, credential_redis, app_factory):
    """The third prefix is what pins a plaintext to its subject kind."""
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.open_api.domain.models.api_credential import HOSTED_APP_TOKEN_PREFIX, KEY_SECRET_LENGTH

    app, _ = await app_factory(state="online")
    plaintext = await AppRuntimeCredentialService.issue(app.id)

    assert plaintext.startswith(HOSTED_APP_TOKEN_PREFIX)
    assert len(plaintext) == len(HOSTED_APP_TOKEN_PREFIX) + KEY_SECRET_LENGTH


async def test_issue_authenticates_and_reports_the_application_identity(
    publish_db, credential_redis, app_factory, owner_user, hosted_app_resolver
):
    """The principal a hosted application authenticates as (F051 design D7 consumes this)."""
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.open_api.domain.models.api_credential import SUBJECT_KIND_HOSTED_APP
    from bisheng.open_api.domain.services.credential_validator import validate_bearer

    app, _ = await app_factory(state="online")
    plaintext = await AppRuntimeCredentialService.issue(app.id)

    principal = await validate_bearer(f"Bearer {plaintext}")

    assert principal.actor_kind == SUBJECT_KIND_HOSTED_APP
    assert principal.actor_id == await _subject_id(app.id)
    assert principal.actor_name == app.name
    # The uuid, because ``actor_id`` cannot hold it — this is what a caller
    # joins an application by.
    assert principal.subject_ref == app.id
    assert principal.tenant_id == ROOT_TENANT_ID
    assert principal.resource_owner_user_id == owner_user.user_id
    assert principal.authorization_subject_type == "user"
    assert principal.authorization_subject_id == owner_user.user_id
    # The accessing user arrives per request on the OBO token, never from the
    # credential: a value here would be a full-visibility fallback for the
    # capability bus to fall back to (AC-52).
    assert principal.effective_user_id is None
    assert principal.mode == "S"


async def test_reissue_revokes_the_previous_key_and_keeps_one_live(
    publish_db, credential_redis, app_factory, hosted_app_resolver
):
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError
    from bisheng.open_api.domain.models.api_credential import REVOKE_REASON_REISSUED
    from bisheng.open_api.domain.repositories.credential_repository import CredentialRepository
    from bisheng.open_api.domain.services.credential_validator import validate_bearer

    app, _ = await app_factory(state="online")
    first = await AppRuntimeCredentialService.issue(app.id)
    second = await AppRuntimeCredentialService.issue(app.id)

    assert first != second
    subject_id = await _subject_id(app.id)
    assert len(await _live_credentials(subject_id)) == 1

    from bisheng.open_api.domain.models.api_credential import SUBJECT_KIND_HOSTED_APP

    rows = await CredentialRepository.list_by_subject(SUBJECT_KIND_HOSTED_APP, subject_id)
    revoked = [row for row in rows if row.revoked_at is not None]
    assert [row.revoke_reason for row in revoked] == [REVOKE_REASON_REISSUED]

    with pytest.raises(OpenApiCredentialInvalidError):
        await validate_bearer(f"Bearer {first}")
    assert (await validate_bearer(f"Bearer {second}")).subject_ref == app.id


async def test_reissue_evicts_the_previous_cache_entry(publish_db, credential_redis, app_factory, hosted_app_resolver):
    """ "The row says revoked" is not the fact INV-28 needs — the cache entry is."""
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.open_api.domain.services.credential_service import CREDENTIAL_CACHE_KEY, hash_token
    from bisheng.open_api.domain.services.credential_validator import validate_bearer

    app, _ = await app_factory(state="online")
    first = await AppRuntimeCredentialService.issue(app.id)
    await validate_bearer(f"Bearer {first}")
    cache_key = CREDENTIAL_CACHE_KEY.format(hash_token(first))
    assert cache_key in credential_redis.values

    await AppRuntimeCredentialService.issue(app.id)
    assert cache_key not in credential_redis.values


async def test_revocation_bound_is_five_seconds(monkeypatch):
    """INV-28 has no poller behind it — the clamped cache TTL is the mechanism."""
    from bisheng.app_publish.domain.services.app_credential_service import (
        REVOCATION_BOUND_SECONDS,
        assert_revocation_bound,
    )
    from bisheng.common.services.config_service import settings
    from bisheng.core.config.open_platform import OpenApiConf

    assert assert_revocation_bound() <= REVOCATION_BOUND_SECONDS
    # A deployment that configures a longer TTL is clamped by the settings
    # model, not merely warned about.
    assert OpenApiConf(credential_cache_ttl_seconds=3600).credential_cache_ttl_seconds == REVOCATION_BOUND_SECONDS

    monkeypatch.setattr(settings.open_api, "credential_cache_ttl_seconds", REVOCATION_BOUND_SECONDS + 1)
    with pytest.raises(AssertionError):
        assert_revocation_bound()


async def test_issue_for_a_missing_application_is_16291(publish_db, credential_redis):
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.common.errcode.app_publish import AppRuntimeSubjectUnavailableError

    with pytest.raises(AppRuntimeSubjectUnavailableError) as excinfo:
        await AppRuntimeCredentialService.issue("no-such-app")
    assert excinfo.value.code == 16291


async def test_issue_for_a_deleted_application_is_16291(publish_db, credential_redis, app_factory):
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.common.errcode.app_publish import AppRuntimeSubjectUnavailableError

    app, _ = await app_factory(state="online")
    await _set_state(publish_db, app.id, "deleted")

    with pytest.raises(AppRuntimeSubjectUnavailableError):
        await AppRuntimeCredentialService.issue(app.id)


async def test_delegate_can_never_be_issued_to_an_application(publish_db, credential_redis, app_factory):
    """``delegate`` is a service-account-only shape; an application acting for a human is not a thing."""
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.common.errcode.open_api import OpenApiDelegateConfigurationInvalidError

    app, _ = await app_factory(state="online")
    with pytest.raises(OpenApiDelegateConfigurationInvalidError):
        await AppRuntimeCredentialService.issue(app.id, scopes=["delegate"])


# ---------------------------------------------------------------------------
# AC-58 — offline deactivates, deletion revokes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", ["stopped", "pending_capacity", "draft", "deleted"])
async def test_a_not_online_application_cannot_authenticate(
    publish_db, credential_redis, app_factory, hosted_app_resolver, state
):
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError
    from bisheng.open_api.domain.services.credential_validator import validate_bearer

    app, _ = await app_factory(state="online")
    plaintext = await AppRuntimeCredentialService.issue(app.id)
    await _set_state(publish_db, app.id, state)
    # Drop the cached principal: production waits out the clamped TTL instead,
    # which is the same thing at a coarser granularity.
    credential_redis.values.clear()

    with pytest.raises(OpenApiCredentialInvalidError):
        await validate_bearer(f"Bearer {plaintext}")


async def test_the_same_key_works_again_after_a_resume(publish_db, credential_redis, app_factory, hosted_app_resolver):
    """Offline is subject deactivation, not revocation (AC-58): no re-publish to come back."""
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError
    from bisheng.open_api.domain.services.credential_validator import validate_bearer

    app, _ = await app_factory(state="online")
    plaintext = await AppRuntimeCredentialService.issue(app.id)

    await _set_state(publish_db, app.id, "stopped")
    credential_redis.values.clear()
    with pytest.raises(OpenApiCredentialInvalidError):
        await validate_bearer(f"Bearer {plaintext}")

    await _set_state(publish_db, app.id, "online")
    credential_redis.values.clear()
    assert (await validate_bearer(f"Bearer {plaintext}")).subject_ref == app.id

    # And nothing was revoked on the way — a stop that revoked would make the
    # resume silently useless.
    assert len(await _live_credentials(await _subject_id(app.id))) == 1


async def test_delete_hook_revokes_the_runtime_credential(
    publish_db, credential_redis, app_factory, hosted_app_resolver, owner_user
):
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.app_runtime.domain.services import lifecycle_hooks
    from bisheng.open_api.domain.models.api_credential import (
        REVOKE_REASON_SUBJECT_DELETED,
        SUBJECT_KIND_HOSTED_APP,
    )
    from bisheng.open_api.domain.repositories.credential_repository import CredentialRepository

    app, _ = await app_factory(state="stopped")
    await AppRuntimeCredentialService.issue(app.id)
    subject_id = await _subject_id(app.id)
    assert len(await _live_credentials(subject_id)) == 1

    failures = await lifecycle_hooks.on_app_deleted(
        app_id=app.id, actor_user_id=owner_user.user_id, tenant_id=ROOT_TENANT_ID
    )

    assert failures == []
    assert await _live_credentials(subject_id) == []

    rows = await CredentialRepository.list_by_subject(SUBJECT_KIND_HOSTED_APP, subject_id)
    assert {row.revoke_reason for row in rows} == {REVOKE_REASON_SUBJECT_DELETED}


async def test_revoking_an_application_that_never_had_a_credential_is_silent(publish_db, credential_redis, app_factory):
    """The deletion hook must not turn a completed deletion into a failure."""
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService

    app, _ = await app_factory(state="stopped")
    assert await AppRuntimeCredentialService.revoke(app.id) == 0
    assert await AppRuntimeCredentialService.revoke(app.id) == 0


async def test_revoking_one_application_leaves_a_sibling_of_the_same_owner_alive(
    publish_db, credential_redis, app_factory, hosted_app_resolver, owner_user
):
    """The reason ``hosted_app_subject`` exists instead of reusing ``owner_user_id``."""
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.open_api.domain.services.credential_validator import validate_bearer

    first, _ = await app_factory(state="online", owner_user_id=owner_user.user_id)
    second, _ = await app_factory(state="online", owner_user_id=owner_user.user_id)
    await AppRuntimeCredentialService.issue(first.id)
    second_key = await AppRuntimeCredentialService.issue(second.id)
    assert await _subject_id(first.id) != await _subject_id(second.id)

    await AppRuntimeCredentialService.revoke(first.id)

    assert await _live_credentials(await _subject_id(first.id)) == []
    assert len(await _live_credentials(await _subject_id(second.id))) == 1
    assert (await validate_bearer(f"Bearer {second_key}")).subject_ref == second.id


async def test_the_subject_surrogate_is_stable_across_reissues(publish_db, credential_redis, app_factory):
    """A surrogate that moved would orphan the audit rows that point at it."""
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService

    app, _ = await app_factory(state="online")
    await AppRuntimeCredentialService.issue(app.id)
    before = await _subject_id(app.id)
    await AppRuntimeCredentialService.issue(app.id)
    assert await _subject_id(app.id) == before


# ---------------------------------------------------------------------------
# AC-59 — no surface, and not among service accounts
# ---------------------------------------------------------------------------


async def test_hosted_app_credentials_are_invisible_to_the_service_account_console(
    publish_db, credential_redis, app_factory
):
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.open_api.domain.models.api_credential import (
        SUBJECT_KIND_HOSTED_APP,
        SUBJECT_KIND_SERVICE_ACCOUNT,
    )
    from bisheng.open_api.domain.repositories.credential_repository import CredentialRepository

    app, _ = await app_factory(state="online")
    await AppRuntimeCredentialService.issue(app.id)
    subject_id = await _subject_id(app.id)

    # The console reads by subject kind; the application's surrogate happens to
    # collide with a service-account id often enough to be worth asserting.
    assert await CredentialRepository.list_by_subject(SUBJECT_KIND_SERVICE_ACCOUNT, subject_id) == []
    assert len(await CredentialRepository.list_by_subject(SUBJECT_KIND_HOSTED_APP, subject_id)) == 1


def test_no_api_endpoint_mentions_the_hosted_app_subject_kind():
    """AC-59 is the absence of a surface; absences are only testable by reading the tree.

    Scans both API layers that could grow one — the Open API management
    endpoints and F055's own — for any reference to the subject kind. The
    credential is issued from the publish pipeline's service layer and nowhere
    else.
    """
    import bisheng

    root = pathlib.Path(bisheng.__file__).parent
    offenders = []
    for api_dir in (root / "open_api" / "api", root / "app_publish" / "api", root / "app_runtime" / "api"):
        for path in api_dir.rglob("*.py"):
            text = path.read_text()
            if "hosted_app" in text or "SUBJECT_KIND_HOSTED_APP" in text or "HOSTED_APP_TOKEN_PREFIX" in text:
                offenders.append(str(path.relative_to(root)))
    assert offenders == [], f"AC-59: no endpoint may expose hosted-app runtime credentials — {offenders}"


def test_the_only_issuer_is_the_publish_pipeline_service():
    """One writer, so "who can mint an application token" stays answerable."""
    import bisheng

    root = pathlib.Path(bisheng.__file__).parent
    issuer = "app_publish/domain/services/app_credential_service.py"
    callers = []
    for path in root.rglob("*.py"):
        relative = str(path.relative_to(root))
        if relative in {issuer, "open_api/domain/models/api_credential.py"}:
            continue
        text = path.read_text()
        if "SUBJECT_KIND_HOSTED_APP" in text and "CredentialService.issue" in text:
            callers.append(relative)
    assert callers == [], f"only {issuer} may issue a hosted-app credential — {callers}"


# ---------------------------------------------------------------------------
# AC-60 — a disabled owner does not stop the application
# ---------------------------------------------------------------------------


async def test_a_disabled_owner_account_does_not_break_the_application(
    publish_db, credential_redis, app_factory, owner_user, hosted_app_resolver
):
    from sqlmodel import select

    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.open_api.domain.services.credential_validator import validate_bearer
    from bisheng.user.domain.models.user import User

    app, _ = await app_factory(state="online")
    plaintext = await AppRuntimeCredentialService.issue(app.id)

    async with publish_db() as session:
        user = (await session.exec(select(User).where(User.user_id == owner_user.user_id))).first()
        user.delete = 1
        session.add(user)
        await session.commit()
    credential_redis.values.clear()

    principal = await validate_bearer(f"Bearer {plaintext}")
    assert principal.resource_owner_user_id == owner_user.user_id


def test_resolution_never_reads_the_user_table():
    """AC-60 as a structural fact rather than one seeded scenario.

    A future "also check the owner is active" line would pass the test above
    only until somebody disabled an owner in production, so the import surface
    is pinned instead.
    """
    import bisheng

    source = (
        pathlib.Path(bisheng.__file__).parent / "app_publish" / "domain" / "services" / "app_credential_service.py"
    ).read_text()
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert not any("user" in module.split(".") for module in imported), (
        f"the runtime credential must resolve without the user row (AC-60); imports: {sorted(imported)}"
    )


# ---------------------------------------------------------------------------
# Fail-closed edges
# ---------------------------------------------------------------------------


async def test_without_the_resolver_a_hosted_app_key_is_refused(publish_db, credential_redis, app_factory):
    """F049 design D2: an unregistered subject kind is refused on ``/api/v2``."""
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError
    from bisheng.open_api.domain.models.api_credential import SUBJECT_KIND_HOSTED_APP
    from bisheng.open_api.domain.services.credential_validator import SUBJECT_RESOLVERS, validate_bearer

    assert SUBJECT_KIND_HOSTED_APP not in SUBJECT_RESOLVERS
    app, _ = await app_factory(state="online")
    plaintext = await AppRuntimeCredentialService.issue(app.id)

    with pytest.raises(OpenApiCredentialInvalidError):
        await validate_bearer(f"Bearer {plaintext}")


async def test_a_service_account_prefix_cannot_present_a_hosted_app_row(
    publish_db, credential_redis, app_factory, hosted_app_resolver
):
    """The prefix pin, exercised against a real row rather than the helper."""
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError
    from bisheng.open_api.domain.models.api_credential import (
        HOSTED_APP_TOKEN_PREFIX,
        SERVICE_ACCOUNT_KEY_PREFIX,
    )
    from bisheng.open_api.domain.services.credential_validator import validate_bearer

    app, _ = await app_factory(state="online")
    plaintext = await AppRuntimeCredentialService.issue(app.id)
    disguised = SERVICE_ACCOUNT_KEY_PREFIX + plaintext[len(HOSTED_APP_TOKEN_PREFIX) :]

    with pytest.raises(OpenApiCredentialInvalidError):
        await validate_bearer(f"Bearer {disguised}")


async def test_a_credential_whose_application_moved_tenant_is_refused(
    publish_db, credential_redis, app_factory, hosted_app_resolver
):
    """``app.tenant_id`` and the credential's tenant must agree, as for service accounts."""
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError
    from bisheng.database.models.app import AppDao
    from bisheng.open_api.domain.services.credential_validator import validate_bearer

    app, _ = await app_factory(state="online")
    plaintext = await AppRuntimeCredentialService.issue(app.id)

    async with publish_db() as session:
        row = await AppDao.aget(session, app.id)
        row.tenant_id = SUB_TENANT_ID
        session.add(row)
        await session.commit()
    credential_redis.values.clear()

    with pytest.raises(OpenApiCredentialInvalidError):
        await validate_bearer(f"Bearer {plaintext}")


def test_the_check_constraint_lists_every_subject_kind():
    """Model constant and DB constraint are one lockstep; drift rejects inserts at runtime."""
    from bisheng.open_api.domain.models.api_credential import CREDENTIAL_SUBJECT_KINDS, ApiCredential

    constraint = next(
        arg for arg in ApiCredential.__table_args__ if getattr(arg, "name", None) == "ck_api_credential_subject_kind"
    )
    text = str(constraint.sqltext)
    for kind in CREDENTIAL_SUBJECT_KINDS:
        assert f"'{kind}'" in text, f"{kind} is in CREDENTIAL_SUBJECT_KINDS but not in the CHECK constraint"


def test_every_subject_kind_has_a_prefix():
    """A kind without a prefix authenticates against nothing — assert that stays intentional."""
    from bisheng.open_api.domain.models.api_credential import CREDENTIAL_SUBJECT_KINDS
    from bisheng.open_api.domain.services.credential_service import credential_prefix
    from bisheng.open_api.domain.services.credential_validator import _SUBJECT_KIND_PREFIXES

    assert set(_SUBJECT_KIND_PREFIXES) == set(CREDENTIAL_SUBJECT_KINDS)
    for kind, prefix in _SUBJECT_KIND_PREFIXES.items():
        assert credential_prefix(kind) == prefix
    assert len(set(_SUBJECT_KIND_PREFIXES.values())) == len(_SUBJECT_KIND_PREFIXES)


async def test_composition_registers_the_resolver_idempotently(hosted_app_resolver):
    from bisheng.app_publish.composition import on_app_deleted_revoke_credential, register
    from bisheng.app_publish.domain.services.app_credential_service import resolve_hosted_app
    from bisheng.app_runtime.domain.services import lifecycle_hooks
    from bisheng.open_api.domain.models.api_credential import SUBJECT_KIND_HOSTED_APP

    register()
    assert hosted_app_resolver[SUBJECT_KIND_HOSTED_APP] is resolve_hosted_app
    assert lifecycle_hooks._hooks.count(on_app_deleted_revoke_credential) == 1


def test_the_injection_variable_name_is_the_one_the_contract_names():
    """F051 / F053 / F054 all reference this literal; it is a cross-feature contract."""
    from bisheng.app_publish.domain.services.app_credential_service import HOSTED_APP_TOKEN_ENV

    assert HOSTED_APP_TOKEN_ENV == "BISHENG_APP_TOKEN"
