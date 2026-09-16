"""Runtime credential of a hosted application (F055 T055 / AC-57 … AC-60).

One sentence: a published application authenticates to ``/api/v2`` with a
``bs-app-`` key that the publish pipeline issues for it, and there is no other
way to get one, look at one, or throw one away.

The shape of the whole thing:

* **Issuance is re-issuance.** :meth:`AppRuntimeCredentialService.issue` always
  revokes whatever the application held first, then mints one key and returns
  the plaintext exactly once — the caller injects it as ``BISHENG_APP_TOKEN``
  into the container it is about to start (AC-57). Nothing persists the
  plaintext, so "re-read the app's token" is not a thing that can exist.
* **Going offline is subject deactivation, not revocation** (AC-58). The
  resolver refuses while the application is not ``online``; resuming makes the
  same key work again, with no new state enum and no re-issue. The refusal
  takes effect within ``open_api.credential_cache_ttl_seconds``, which the
  settings model caps at 5 — that cap **is** INV-28's five-second bound, which
  is why :func:`assert_revocation_bound` exists to say so out loud.
  The refusal has **two** halves, and one without the other is a hole: the
  resolver guards admission, and :func:`assert_hosted_app_executable` guards the
  Celery leg, where a task accepted seconds before the stop would otherwise run
  with the application's authority long after it.
* **Deletion revokes** (AC-58), through F054's app-deleted hook, wired in
  ``app_publish/composition.py``.
* **There is no management surface** (AC-59). These rows are a distinct
  ``subject_kind``, so the service-account console — which queries
  ``subject_kind = 'service_account'`` — cannot show them, and no endpoint in
  this module or ``open_api`` issues, lists or revokes them.

Two decisions worth not re-litigating:

* **Authentication-time refusal is ``26002``, not ``16291``.** A credential for
  a stopped / deleted / foreign-tenant application is simply not a valid
  credential, and answering with a distinct code would turn a stale token into
  a probe for an application's state. ``16291``
  (:class:`AppRuntimeSubjectUnavailableError`) is raised on the *issuance* path
  instead, where the caller is the pipeline and the fact "this app cannot be a
  credential subject" is actionable.
* **``effective_user_id`` stays ``None``.** The application acts as itself; the
  *accessing user* arrives per request on the OBO token (F051 design D7) and is
  never baked into the credential. Setting it to the owner here would give the
  capability bus a full-visibility fallback to fall back to, which is exactly
  what AC-52 forbids. ``authorization_subject_*`` does point at the owner,
  because the owner's grants are the ceiling the capability whitelist narrows
  (design D13).
"""

from __future__ import annotations

from collections.abc import Sequence

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.app_publish.domain.models.hosted_app_subject import HostedAppSubject, HostedAppSubjectDao
from bisheng.app_runtime.domain.constants import AppState
from bisheng.common.errcode.app_publish import AppRuntimeSubjectUnavailableError
from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError, OpenApiDelegateConfigurationInvalidError
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.database.models.app import App, AppDao
from bisheng.open_api.domain.context import OpenApiExecutionSnapshot, OpenApiPrincipal
from bisheng.open_api.domain.models.api_credential import (
    REVOKE_REASON_REISSUED,
    REVOKE_REASON_SUBJECT_DELETED,
    SUBJECT_KIND_HOSTED_APP,
    ApiCredential,
)
from bisheng.open_api.domain.schemas.credential import KeyIssueRequest
from bisheng.open_api.domain.scopes import DELEGATE_SCOPE_CODE
from bisheng.open_api.domain.services.credential_service import CredentialService

#: Environment variable the runtime credential is injected under (design D13).
#: F051 names ``OPENAI_API_KEY`` / ``BISHENG_MODEL_BASE_URL`` for the model face
#: and takes this one's *value* as a plain bearer token.
HOSTED_APP_TOKEN_ENV = "BISHENG_APP_TOKEN"

#: INV-28: a revoked or deactivated runtime credential stops working within
#: five seconds. Nothing polls to make that true — the credential cache TTL is
#: the whole mechanism, and ``OpenApiConf.cap_credential_cache_ttl`` clamps it.
REVOCATION_BOUND_SECONDS = 5


def assert_revocation_bound() -> int:
    """Return the effective credential cache TTL, refusing one above the bound.

    Called by the test suite rather than at runtime: the point is to fail a
    change that raises the cap, not to add a startup check for a value the
    settings model already clamps.
    """
    ttl = int(settings.open_api.credential_cache_ttl_seconds)
    if ttl > REVOCATION_BOUND_SECONDS:
        raise AssertionError(
            f"open_api.credential_cache_ttl_seconds={ttl} exceeds the {REVOCATION_BOUND_SECONDS}s "
            "revocation bound (F055 INV-28)"
        )
    return ttl


async def load_subject_app(app_id: str) -> App | None:
    """The application behind a subject, or ``None`` when it cannot hold one.

    Bypasses the tenant filter on purpose: issuance runs inside the publish
    pipeline and authentication runs before any tenant context exists. The row's
    own ``tenant_id`` is the authority from here on, and
    :func:`resolve_hosted_app` compares it against the credential's.
    """
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            app = await AppDao.aget(session, app_id)
    if app is None or app.state == AppState.DELETED.value:
        return None
    return app


class AppRuntimeCredentialService:
    """Issue / re-issue / revoke the runtime credential of one hosted application."""

    @classmethod
    async def issue(cls, app_id: str, *, scopes: Sequence[str] = ()) -> str:
        """Re-issue this application's runtime credential; return the plaintext.

        ``scopes`` is derived by the capability bus from the version's
        declaration (T056 / T057) and passed in — this service deliberately does
        not know what a model or a knowledge base is. An empty sequence is the
        honest answer while the capability bus is not deployed: the application
        gets an identity and no permission at all.

        Raises :class:`AppRuntimeSubjectUnavailableError` (16291) when the
        application cannot be a credential subject — missing or already deleted.
        """
        app = await load_subject_app(app_id)
        if app is None:
            raise AppRuntimeSubjectUnavailableError(app_id=app_id, reason="app_missing")

        # Every reason to refuse the *request* is established before anything is
        # revoked. ``CredentialService.issue`` validates the same two things
        # again a few lines down, but by then the previous key is already gone —
        # a capability declaration that derives an unknown scope would otherwise
        # take the running container's credential with it and leave the
        # application unauthenticated until someone publishes again.
        requested = CredentialService.validate_scopes(list(scopes))
        if DELEGATE_SCOPE_CODE in requested:
            # An application acting on a human's behalf is not a shape this
            # subject has; ``_delegate_entries`` refuses it too, only later.
            raise OpenApiDelegateConfigurationInvalidError()

        subject = await cls._ensure_subject(app.id)

        # Revoke first: a failure between the two leaves the application with no
        # working key, which the next publish fixes. The other order would leave
        # two live keys with no record of which container holds which.
        revoked = await cls._revoke_subject(subject.id, reason=REVOKE_REASON_REISSUED)
        issued = await CredentialService.issue(
            tenant_id=int(app.tenant_id or 0),
            subject_kind=SUBJECT_KIND_HOSTED_APP,
            subject_id=int(subject.id),
            request=KeyIssueRequest(name=cls._credential_name(app), scopes=requested, expires_at=None),
            created_by=None,
        )
        logger.info(
            "app_publish.runtime_credential_issued app_id={} subject_id={} scopes={} revoked={}",
            app.id,
            subject.id,
            list(scopes),
            revoked,
        )
        return issued.plaintext

    @classmethod
    async def revoke(cls, app_id: str, *, reason: str = REVOKE_REASON_SUBJECT_DELETED) -> int:
        """Revoke every live runtime credential of one application; return how many.

        Idempotent, and silent about an application that never had one — the
        deletion hook must not fail a completed deletion (F054 lifecycle_hooks).
        """
        subject = await cls._find_subject(app_id)
        if subject is None:
            return 0
        count = await cls._revoke_subject(subject.id, reason=reason)
        if count:
            logger.info(
                "app_publish.runtime_credential_revoked app_id={} subject_id={} count={} reason={}",
                app_id,
                subject.id,
                count,
                reason,
            )
        return count

    # ------------------------------------------------------------------
    # subject bookkeeping
    # ------------------------------------------------------------------

    @staticmethod
    async def _find_subject(app_id: str) -> HostedAppSubject | None:
        async with get_async_db_session() as session:
            return await HostedAppSubjectDao.aget_by_app(session, app_id)

    @classmethod
    async def _ensure_subject(cls, app_id: str) -> HostedAppSubject:
        existing = await cls._find_subject(app_id)
        if existing is not None:
            return existing
        try:
            async with get_async_db_session() as session:
                row = await HostedAppSubjectDao.acreate(session, app_id)
                await session.commit()
        except IntegrityError:
            # ``uk_hosted_app_subject_app`` did its job: a concurrent publish of
            # the same application inserted first. Read that row rather than
            # failing the publish — the surrogate has to be *one* per
            # application, and which of the two racers created it is immaterial.
            existing = await cls._find_subject(app_id)
            if existing is None:
                raise
            return existing
        return row

    @staticmethod
    async def _revoke_subject(subject_id: int, *, reason: str) -> int:
        """Revoke by surrogate, outside the tenant filter.

        ``subject_id`` is globally unique per application and the caller has
        already resolved the application, so the filter would only be able to
        *hide* rows that must be revoked — a stop that silently left a key alive
        because the ambient tenant was a sibling is the failure this avoids.
        """
        with bypass_tenant_filter():
            return await CredentialService.revoke_by_subject(SUBJECT_KIND_HOSTED_APP, int(subject_id), reason=reason)

    @staticmethod
    def _credential_name(app: App) -> str:
        # Never shown in a management list (AC-59); it exists for audit rows and
        # for a human reading the table during an incident.
        return f"hosted-app:{app.slug}"[:128]


async def resolve_hosted_app(row: ApiCredential) -> OpenApiPrincipal:
    """``SUBJECT_RESOLVERS['hosted_app']`` — registered from the composition root.

    Every refusal is the same ``26002``: see the module docstring for why the
    application's state must not be readable from the outcome.
    """
    async with get_async_db_session() as session:
        subject = await HostedAppSubjectDao.aget(session, int(row.subject_id))
    if subject is None:
        raise OpenApiCredentialInvalidError()

    app = await load_subject_app(subject.app_id)
    if app is None or int(app.tenant_id or 0) != int(row.tenant_id or 0):
        raise OpenApiCredentialInvalidError()
    if app.state != AppState.ONLINE.value:
        # AC-58: offline is subject deactivation. The key is still on file and
        # starts working again the moment the application resumes.
        raise OpenApiCredentialInvalidError()

    return OpenApiPrincipal(
        credential_id=row.id,
        actor_kind=SUBJECT_KIND_HOSTED_APP,
        actor_id=int(subject.id),
        actor_name=app.name,
        subject_ref=app.id,
        tenant_id=row.tenant_id,
        # The owner is the authorization ceiling (design D13); a disabled owner
        # account does not stop the application (AC-60), because nothing here
        # reads the user row.
        resource_owner_user_id=int(app.owner_user_id or 0),
        scopes=frozenset(row.scopes or []),
        mode="S",
        authorization_subject_type="user",
        authorization_subject_id=int(app.owner_user_id or 0),
        # Deliberately None — see the module docstring.
        effective_user_id=None,
    )


def assert_hosted_app_executable(credential: ApiCredential, snapshot: OpenApiExecutionSnapshot) -> None:
    """``SUBJECT_EXECUTION_GUARDS['hosted_app']`` — the synchronous twin of
    :func:`resolve_hosted_app`, run when a Celery task restores the identity
    that enqueued it.

    Without it, "the application went offline" would only be true of requests
    that had not been accepted yet: work queued a second before the stop would
    still execute with the application's authority, minutes later (AC-58). Same
    three refusals as the admission path, same ``26002``, and — like the
    admission path — nothing here reads the ``user`` row (AC-60).
    """
    with bypass_tenant_filter(), get_sync_db_session() as session:
        subject = session.exec(
            select(HostedAppSubject).where(HostedAppSubject.id == int(credential.subject_id))
        ).first()
        app = session.exec(select(App).where(App.id == subject.app_id)).first() if subject is not None else None
    if app is None or app.state != AppState.ONLINE.value:
        raise OpenApiCredentialInvalidError()
    if int(app.tenant_id or 0) != int(credential.tenant_id or 0) or int(app.tenant_id or 0) != int(snapshot.tenant_id):
        raise OpenApiCredentialInvalidError()


__all__ = [
    "HOSTED_APP_TOKEN_ENV",
    "REVOCATION_BOUND_SECONDS",
    "AppRuntimeCredentialService",
    "assert_hosted_app_executable",
    "assert_revocation_bound",
    "load_subject_app",
    "resolve_hosted_app",
]
