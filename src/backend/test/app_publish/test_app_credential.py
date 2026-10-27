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
import importlib
import pathlib
from contextlib import contextmanager

import pytest

from test.app_publish.conftest import ROOT_TENANT_ID, SUB_TENANT_ID


@pytest.fixture()
def sync_subject_db(monkeypatch):
    """A **synchronous** SQLite holding just ``app`` + ``hosted_app_subject``.

    The package's async fixture is one aiosqlite connection that a sync engine
    cannot join, and the execution guard runs on the Celery leg where only sync
    sessions exist. So this builds the two tables that guard reads and binds the
    factory by name, exactly as ``_SESSION_PATCH_TARGETS`` binds the async one.

    Yields ``(seed_app, seed_subject)``.
    """
    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, SQLModel, create_engine

    from bisheng.app_publish.domain.models.hosted_app_subject import HostedAppSubject
    from bisheng.database.models.app import App

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine, tables=[App.__table__, HostedAppSubject.__table__])

    @contextmanager
    def _session():
        with Session(engine) as session:
            yield session

    module = importlib.import_module("bisheng.app_publish.domain.services.app_credential_service")
    monkeypatch.setattr(module, "get_sync_db_session", _session)

    def _seed(*, app_id: str = "app-sync", state: str = "online", tenant_id: int = ROOT_TENANT_ID) -> int:
        with Session(engine) as session:
            session.add(
                App(
                    id=app_id,
                    slug=app_id,
                    name="sync app",
                    owner_user_id=7,
                    tenant_id=tenant_id,
                    state=state,
                )
            )
            subject = HostedAppSubject(app_id=app_id)
            session.add(subject)
            session.commit()
            return int(subject.id)

    return _seed


def _hosted_credential(*, subject_id: int, tenant_id: int = ROOT_TENANT_ID):
    from bisheng.open_api.domain.models.api_credential import SUBJECT_KIND_HOSTED_APP, ApiCredential

    return ApiCredential(
        id=901,
        tenant_id=tenant_id,
        subject_kind=SUBJECT_KIND_HOSTED_APP,
        subject_id=subject_id,
        name="hosted-app:sync",
        key_prefix="bs-app-",
        last4="abcd",
        token_hash="0" * 64,
        scopes=[],
    )


def _hosted_snapshot(*, subject_id: int, tenant_id: int = ROOT_TENANT_ID):
    from bisheng.open_api.domain.context import OpenApiExecutionSnapshot

    return OpenApiExecutionSnapshot(
        tenant_id=tenant_id,
        actor_kind="hosted_app",
        actor_id=subject_id,
        authorization_subject_type="user",
        authorization_subject_id=7,
        resource_owner_user_id=7,
        effective_user_id=None,
        mode="S",
        credential_id=901,
        trace_id="trace-hosted",
        channel="open_api_v2",
    )


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


async def _audit_rows(publish_db, action: str | None = None) -> list:
    """Rows actually present in ``auditlog``, optionally filtered by action.

    Reads the table rather than capturing ``ainsert_v2`` calls on purpose. The
    defect these tests exist for was not "the call was made with the wrong
    arguments" — it was that the two automatic paths passed no
    ``audit_operator`` at all, so ``_audit`` was never reached and the row never
    existed. A captured-call fixture asserts the same thing only as long as
    somebody remembers to install it; the table cannot be fooled.

    ``bypass_tenant_filter`` for the same reason ``ainsert_v2`` writes under it:
    the read must see rows regardless of whichever tenant the publish left in
    the ContextVar.
    """
    from sqlmodel import select

    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.database.models.audit_log import AuditLog

    with bypass_tenant_filter():
        async with publish_db() as session:
            rows = (await session.exec(select(AuditLog))).all()
    return [row for row in rows if action is None or row.action == action]


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


@pytest.mark.parametrize(
    ("scopes", "error_name"),
    [
        (["not:a:scope"], "OpenApiUnknownScopeError"),
        (["delegate"], "OpenApiDelegateConfigurationInvalidError"),
    ],
)
async def test_a_refused_reissue_leaves_the_running_key_alive(
    publish_db, credential_redis, app_factory, hosted_app_resolver, scopes, error_name
):
    """A rejected scope must not take the container's current credential with it.

    Re-issue revokes before it mints, so every reason to refuse the *request*
    has to be established first — otherwise a capability declaration that
    derives a scope this deployment does not offer would leave a running
    application unauthenticated until somebody published again.
    """
    import bisheng.common.errcode.open_api as open_api_errors
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.open_api.domain.services.credential_validator import validate_bearer

    app, _ = await app_factory(state="online")
    live = await AppRuntimeCredentialService.issue(app.id)

    with pytest.raises(getattr(open_api_errors, error_name)):
        await AppRuntimeCredentialService.issue(app.id, scopes=scopes)

    credential_redis.values.clear()
    assert (await validate_bearer(f"Bearer {live}")).subject_ref == app.id
    assert len(await _live_credentials(await _subject_id(app.id))) == 1


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
# AC-58, the audit half — 「两者事件计审计」 / PRD-1 GOV-08
# ---------------------------------------------------------------------------
#
# The credential-state assertions above all passed while these rows were never
# written: both automatic paths called the credential base without an
# ``audit_operator``, and ``_audit`` only fires when one is present. So the
# whole feature was observable to the platform as two ``logger.info`` lines and
# nothing in the audit table.


ISSUE_ACTION = "open_api.api_key.issue"
REVOKE_ACTION = "open_api.api_key.revoke"


def test_the_audit_actions_are_ones_the_audit_page_can_show():
    """Reusing the human-issued key's action names is the whole point.

    GOV-04 files automatic issuance under 「key 签发/吊销」, and these two names
    are already in the UI whitelist, in the platform's log filter and in the
    three ``bs.json`` copies. A hosted-app-specific action would have to land in
    all four at once or become an event that writes and can never be found —
    this test is what stops somebody "clarifying" the names later.
    """
    from bisheng.database.models.audit_log import _UI_VISIBLE_V2_ACTIONS

    assert ISSUE_ACTION in _UI_VISIBLE_V2_ACTIONS
    assert REVOKE_ACTION in _UI_VISIBLE_V2_ACTIONS


async def test_issuing_the_runtime_credential_writes_one_audit_row(publish_db, credential_redis, app_factory):
    """AC-58 / GOV-08: the signing event is on the record, attributed to the platform."""
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService

    app, _ = await app_factory(state="online")
    await AppRuntimeCredentialService.issue(app.id, scopes=["knowledge:read"])

    rows = await _audit_rows(publish_db, ISSUE_ACTION)
    assert len(rows) == 1
    row = rows[0]
    # No natural person triggered this, so none is borrowed: the platform's
    # system-trigger convention, which the table renders as "system".
    assert row.operator_id == 0
    assert row.operator_name == "system"
    assert row.tenant_id == ROOT_TENANT_ID
    assert row.target_type == "api_credential"
    # What separates this row from a human-issued service-account key on the
    # very same action name.
    assert row.audit_metadata["subject_kind"] == "hosted_app"
    assert row.audit_metadata["subject_id"] == await _subject_id(app.id)
    assert row.audit_metadata["scopes"] == ["knowledge:read"]
    # ``_credential_name`` says it exists "for audit rows" — so this is the
    # assertion that makes that comment true.
    assert row.object_name == f"hosted-app:{app.slug}"
    assert row.target_id == str(row.audit_metadata["credential_id"])


async def test_the_delete_hook_audits_the_revocation(
    publish_db, credential_redis, app_factory, hosted_app_resolver, owner_user
):
    """The gap ``test_delete_hook_revokes_the_runtime_credential`` left open.

    That test asserts the credential's *state*, which was already correct. The
    revocation event was the part nobody could see.
    """
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.app_runtime.domain.services import lifecycle_hooks

    app, _ = await app_factory(state="stopped")
    await AppRuntimeCredentialService.issue(app.id)

    failures = await lifecycle_hooks.on_app_deleted(
        app_id=app.id, actor_user_id=owner_user.user_id, tenant_id=ROOT_TENANT_ID
    )
    assert failures == []

    rows = await _audit_rows(publish_db, REVOKE_ACTION)
    assert len(rows) == 1
    assert rows[0].operator_id == 0
    assert rows[0].operator_name == "system"
    assert rows[0].audit_metadata["subject_kind"] == "hosted_app"
    assert rows[0].audit_metadata["subject_id"] == await _subject_id(app.id)


async def test_a_reissue_audits_both_the_revocation_and_the_new_key(publish_db, credential_redis, app_factory):
    """Issuance is re-issuance, and both halves are events.

    A publish that only recorded the mint would leave "which key was live at
    which moment" unanswerable — precisely the question an incident asks.
    """
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService

    app, _ = await app_factory(state="online")
    await AppRuntimeCredentialService.issue(app.id)
    await AppRuntimeCredentialService.issue(app.id)

    assert len(await _audit_rows(publish_db, ISSUE_ACTION)) == 2
    revoked = await _audit_rows(publish_db, REVOKE_ACTION)
    assert len(revoked) == 1
    assert revoked[0].audit_metadata["subject_kind"] == "hosted_app"


async def test_revoking_an_application_without_a_credential_writes_nothing(publish_db, credential_redis, app_factory):
    """No credential, no event — an empty revocation is not an occurrence."""
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService

    app, _ = await app_factory(state="stopped")
    assert await AppRuntimeCredentialService.revoke(app.id) == 0
    assert await _audit_rows(publish_db) == []


async def test_an_unwritable_audit_row_never_fails_the_publish(
    publish_db, credential_redis, app_factory, hosted_app_resolver, monkeypatch
):
    """Best effort, in the shape ``release_audit`` established.

    By the time the audit runs the key is minted and committed. Letting the
    failure out would 500 the publish *and* lose the plaintext, which is
    returned exactly once and stored nowhere — an application left permanently
    unable to authenticate because a log row could not be written.
    """
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.database.models.audit_log import AuditLogDao
    from bisheng.open_api.domain.services.credential_validator import validate_bearer

    async def _boom(cls, *args, **kwargs):
        raise RuntimeError("auditlog is unreachable")

    monkeypatch.setattr(AuditLogDao, "ainsert_v2", classmethod(_boom))

    app, _ = await app_factory(state="online")
    plaintext = await AppRuntimeCredentialService.issue(app.id)
    assert (await validate_bearer(f"Bearer {plaintext}")).subject_ref == app.id

    # And the revocation leg survives it too, so a deletion still completes.
    assert await AppRuntimeCredentialService.revoke(app.id) == 1


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


#: API-layer files allowed to name the subject kind at all, and why.
#:
#: The rule AC-59 states is "no endpoint exposes the application's runtime
#: credential" — no listing, no re-issue, no plaintext. **Refusing** the subject
#: is the opposite of exposing it, and route admission has to name it somewhere:
#: F055 T056-T060 made the gate default-deny for this actor kind and marked the
#: two capability faces as the exceptions. Both are still held to the credential
#: half of the rule below, and everything else is still scanned exactly.
_ADMISSION_CONTROL_FILES = {
    # Refuses this subject on every route that did not opt in (26052).
    "open_api/api/dependencies.py",
    # The model face opts in: ``hosted_app=True`` on its three routes.
    "open_api/api/endpoints/model_gateway.py",
}


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
            relative = str(path.relative_to(root))
            # The credential half: never allowed, admission control included.
            if "SUBJECT_KIND_HOSTED_APP" in text or "HOSTED_APP_TOKEN_PREFIX" in text:
                offenders.append(relative)
            elif "hosted_app" in text and relative not in _ADMISSION_CONTROL_FILES:
                offenders.append(relative)
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


# ---------------------------------------------------------------------------
# AC-58, asynchronous leg — a queued task must not outlive the stop
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", ["stopped", "pending_capacity", "draft", "deleted"])
def test_a_queued_task_of_a_stopped_application_is_refused(sync_subject_db, state):
    """The Celery leg re-checks what the synchronous gate checked.

    Admission happens once, at request time; the work it enqueues can run
    minutes later. Without this check "the application is offline" would be
    true only of requests that had not been accepted yet.
    """
    from bisheng.app_publish.domain.services.app_credential_service import assert_hosted_app_executable
    from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError

    subject_id = sync_subject_db(state=state)
    with pytest.raises(OpenApiCredentialInvalidError):
        assert_hosted_app_executable(_hosted_credential(subject_id=subject_id), _hosted_snapshot(subject_id=subject_id))


def test_a_queued_task_of_an_online_application_is_allowed(sync_subject_db):
    from bisheng.app_publish.domain.services.app_credential_service import assert_hosted_app_executable

    subject_id = sync_subject_db(state="online")
    assert_hosted_app_executable(_hosted_credential(subject_id=subject_id), _hosted_snapshot(subject_id=subject_id))


def test_a_queued_task_whose_application_moved_tenant_is_refused(sync_subject_db):
    from bisheng.app_publish.domain.services.app_credential_service import assert_hosted_app_executable
    from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError

    subject_id = sync_subject_db(state="online", tenant_id=SUB_TENANT_ID)
    with pytest.raises(OpenApiCredentialInvalidError):
        assert_hosted_app_executable(
            _hosted_credential(subject_id=subject_id, tenant_id=ROOT_TENANT_ID),
            _hosted_snapshot(subject_id=subject_id, tenant_id=ROOT_TENANT_ID),
        )


def test_a_queued_task_with_no_surrogate_row_is_refused(sync_subject_db):
    from bisheng.app_publish.domain.services.app_credential_service import assert_hosted_app_executable
    from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError

    sync_subject_db(state="online")
    with pytest.raises(OpenApiCredentialInvalidError):
        assert_hosted_app_executable(_hosted_credential(subject_id=4242), _hosted_snapshot(subject_id=4242))


def test_a_subject_kind_without_an_execution_guard_cannot_execute(monkeypatch):
    """Fail-closed default: an unregistered kind is refused, not waved through.

    The pre-F055 shape was an ``if`` / ``elif`` over the two built-in kinds with
    no ``else``, so a third kind would have restored its identity on the worker
    with nothing checked at all.
    """
    from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError
    from bisheng.open_api.domain.services import execution_context

    subject_id = 11
    monkeypatch.setattr(
        execution_context.CredentialRepository,
        "get_for_execution_sync",
        staticmethod(lambda _credential_id: _hosted_credential(subject_id=subject_id)),
    )
    monkeypatch.setattr(execution_context, "SUBJECT_EXECUTION_GUARDS", {})

    with pytest.raises(OpenApiCredentialInvalidError):
        execution_context.validate_execution_snapshot(_hosted_snapshot(subject_id=subject_id))


def test_composition_registers_the_execution_guard(hosted_app_resolver):
    """Resolver and guard are one registration — a process with only the first
    would admit a hosted application and then never re-check it."""
    from bisheng.app_publish.domain.services.app_credential_service import assert_hosted_app_executable
    from bisheng.open_api.domain.models.api_credential import SUBJECT_KIND_HOSTED_APP
    from bisheng.open_api.domain.services.execution_context import SUBJECT_EXECUTION_GUARDS

    assert SUBJECT_EXECUTION_GUARDS[SUBJECT_KIND_HOSTED_APP] is assert_hosted_app_executable


def test_the_injection_variable_name_is_the_one_the_contract_names():
    """F051 / F053 / F054 all reference this literal; it is a cross-feature contract."""
    from bisheng.app_publish.domain.services.app_credential_service import HOSTED_APP_TOKEN_ENV

    assert HOSTED_APP_TOKEN_ENV == "BISHENG_APP_TOKEN"
