"""The entry verdict: who is this, may they enter, and what does the app get told.

app-proxy holds **no** permission logic (D6-C). It asks this service once per
``(session, slug)`` and caches the answer for 3 seconds. Everything security
relevant about ``/apps/{slug}`` therefore lives here, once, and is identical in
the open-source and commercial builds — the Java gateway does not see ``/apps``
at all (K8), so a second copy of these rules would silently diverge.

**The order of the five steps is the information-disclosure contract**, not an
implementation detail (spec §3):

1. is the factory deployed here at all → ``not_enabled``. Answered *before* the
   session check, so an environment without the layer never bounces visitors
   through a login they did not need.
2. is there a valid platform session → ``login``. "Valid" means the platform's
   own middleware chain: token version, account disabled, tenant disabled.
   Decoding the JWT locally and stopping there would skip all three (K7), which
   is precisely how a disabled account keeps working for the length of its
   token's lifetime.
3. does the app exist *and* has it ever been online → ``not_found``. Draft,
   pending, deleted and "no such slug" collapse into one answer (AC-29): any
   difference between them tells a stranger which application names are taken.
4. is the visitor inside the visible scope → ``forbidden``, carrying the app
   name and its owner so the page can say who to ask.
5. is it stopped → ``stopped``, and only for people who passed step 4.

**The permission engine failing is a refusal** (AC-12 / INV-30). There is no
branch here that treats "could not decide" as "let them in".

Identity leaves as *material*, not as headers: app-proxy owns the wire format,
strips the entire ``x-bisheng-`` equivalence class off the inbound request and
then writes this material back on (AC-32). Non-ASCII values are
percent-encoded here because HTTP headers are latin-1 and the usual test
account has an English name, so the bug is invisible until a real user with a
Chinese name opens an app (pit 9).
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import quote

import jwt
from loguru import logger

from bisheng.app_runtime.domain.constants import ENTRY_VISIBLE_STATES, AppState
from bisheng.app_runtime.domain.services.app_access_log_service import schedule_access_record
from bisheng.common.errcode.app_factory import AppPermissionEngineUnavailableError
from bisheng.common.errcode.permission import (
    PermissionInvalidResourceError,
    PermissionServiceUnavailableError,
)
from bisheng.common.errcode.tenant_fga import PermissionBackendUnavailableError
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import App, AppDao
from bisheng.permission.application.business_authorization import check_business_action
from bisheng.utils.http_middleware import (
    _check_is_global_super,
    _decode_jwt_subject,
    _validate_current_session_token,
    _validate_token_version,
)

DECISION_ALLOW = "allow"
DECISION_LOGIN = "login"
DECISION_FORBIDDEN = "forbidden"
DECISION_STOPPED = "stopped"
DECISION_NOT_FOUND = "not_found"
DECISION_NOT_ENABLED = "not_enabled"
#: Could not decide. app-proxy renders a refusal page for it — never a pass.
DECISION_UNAVAILABLE = "unavailable"

#: Audience of the on-behalf-of token. Distinct from any platform audience so a
#: leaked OBO token cannot be replayed as a session (AC-34).
OBO_AUDIENCE = "bisheng-app-obo"

#: Visible-scope action. ``use`` rather than ``runtime.check_visible``: ``use``
#: is what the permission dialog's viewer tier grants, so "who can open it"
#: matches what an owner sees when they share it. ``check_visible`` is wider —
#: it would admit a custom model that granted ``edit`` without ``use`` (D9).
ENTRY_ACTION = "use"


async def authorize_entry(
    *,
    slug: str,
    access_token: str | None,
    request_id: str = "",
    client_ip: str | None = None,
) -> dict[str, Any]:
    """One verdict for one visit. Never raises for a business outcome."""
    if not settings.app_runtime.enabled:
        return {"decision": DECISION_NOT_ENABLED}

    subject = _decode_jwt_subject(access_token) if access_token else None
    if subject is None:
        return {"decision": DECISION_LOGIN, "reason": "no_session"}

    user_id = int(subject.get("user_id") or 0)
    tenant_id = int(subject.get("tenant_id") or 0)
    if not user_id:
        return {"decision": DECISION_LOGIN, "reason": "no_session"}

    session_reason = await _session_invalid_reason(user_id, tenant_id, subject, access_token)
    if session_reason:
        # Answered as "sign in again" rather than "forbidden": the visitor has
        # no usable session, and at this point we have not even looked the app
        # up — saying "forbidden" would imply it exists.
        return {"decision": DECISION_LOGIN, "reason": session_reason}

    app = await _load_app_by_slug(slug)
    if app is None or AppState(app.state) not in ENTRY_VISIBLE_STATES:
        return {"decision": DECISION_NOT_FOUND}

    set_current_tenant_id(int(app.tenant_id or 0))
    actor = await _build_actor(user_id, subject)
    try:
        visible = await check_business_action(
            actor,
            resource_type="app",
            resource_id=app.id,
            action=ENTRY_ACTION,
        )
    except (PermissionServiceUnavailableError, PermissionBackendUnavailableError) as exc:
        logger.error("app_runtime.entry permission engine unavailable slug={} user={}: {}", slug, user_id, exc)
        return {
            "decision": DECISION_UNAVAILABLE,
            "code": AppPermissionEngineUnavailableError.Code,
            "reason": "permission_engine_unavailable",
        }
    except PermissionInvalidResourceError:
        # The F048 target resolver raises this (19003) when the app is not a
        # legitimate target for THIS actor — most commonly a cross-tenant
        # visitor, whom AC-29 says must not even learn the app exists. Answered
        # as NOT_FOUND, not FORBIDDEN. Critically, it must be caught here: it is
        # a BaseErrorCode, so letting it propagate makes the internal endpoint
        # return a body with no ``decision`` field, and app-proxy then
        # fail-closes the visit to a 503 instead of a clean not-found page.
        return {"decision": DECISION_NOT_FOUND}

    owner_name = await _owner_name(app)
    if not visible:
        # Name and owner on purpose: the visitor has been told the app exists
        # (they were given a link to it), so the useful answer is who to ask.
        return {
            "decision": DECISION_FORBIDDEN,
            "app_id": app.id,
            "app_name": app.name,
            "owner_name": owner_name,
            "app_state": app.state,
            # Not identity material — app-proxy injects nothing on a refusal.
            # It is the visitor app-proxy writes into ``app_proxy.request``
            # (design §7): a refusal whose user_id is empty cannot answer
            # "who could not get in", and that is the commonest support call.
            "user_id": user_id,
        }

    if app.state == AppState.STOPPED.value:
        # Only reachable after the visible-scope check — a stranger must not be
        # able to distinguish "stopped" from "does not exist" (AC-29).
        return {
            "decision": DECISION_STOPPED,
            "app_id": app.id,
            "app_name": app.name,
            "owner_name": owner_name,
            "app_state": app.state,
            "user_id": user_id,
        }

    user_name, subject_kind = await _user_facts(user_id, subject)
    material = await _identity_material(
        app=app, user_id=user_id, user_name=user_name, subject_kind=subject_kind, request_id=request_id
    )
    obo_token, obo_expires_at = _issue_obo_token(
        app_id=app.id,
        user_id=user_id,
        tenant_id=int(app.tenant_id or 0),
        subject_kind=material.get("X-BiSheng-Subject-Kind", "human"),
    )
    if obo_token:
        material["X-BiSheng-Access-Token"] = obo_token
    logger.debug("app_runtime.entry allow slug={} user={} ip={}", slug, user_id, client_ip)
    # AC-38: the access record is a side effect of *this* verdict and of no
    # other code path — app-proxy has no database, and only ``allow`` is an
    # entry. Scheduled, not awaited: the write must never delay or fail the
    # answer (design D14-B); the merge window inside collapses repeats.
    schedule_access_record(
        app_id=app.id,
        tenant_id=int(app.tenant_id or 0),
        user_id=user_id,
        user_name=user_name,
        request_id=request_id,
    )
    return {
        "decision": DECISION_ALLOW,
        "app_id": app.id,
        "app_name": app.name,
        "owner_name": owner_name,
        "app_state": app.state,
        "headers": material,
        "obo_token": obo_token,
        # WebSocket lifetime inputs (D6 invariant ①, T081): app-proxy fixes a
        # socket's authorised lifetime at the handshake as
        # ``min(OBO remaining, ws_max_lifetime_seconds)``. Stated here so the
        # cap is this process's config, not a second copy in the proxy's env.
        "obo_expires_at": obo_expires_at,
        "ws_max_lifetime_seconds": int(settings.app_runtime.ws_max_lifetime_seconds),
    }


async def authorize_preview_entry(
    *,
    session: str,
    access_token: str | None,
    request_id: str = "",
    client_ip: str | None = None,
) -> dict[str, Any]:
    """The verdict for ``/apps/preview/{session}`` (F054 AC-37, F055 AC-26 / AC-27).

    Same five-step order as :func:`authorize_entry` and, where it differs, the
    difference is the point:

    * **Step 3 is the preview session, not the slug.** Unknown, reclaimed and
      expired are one answer — ``not_found`` — because the difference would
      tell a stranger that a session id was once real.
    * **Step 4 is "is this *that* approver", not the visible scope.** A preview
      belongs to the person it was raised for and to nobody else: not the
      owner, not another approver on the same request, not a tenant
      administrator. AC-27 says the instance carries the approver's own
      identity, so a second person entering it would be acting as the first.
      (The owner's own way in is the application's real entry; the approval
      exception in NFR-1.2 / INV-36 widens what the *capabilities* inside the
      preview may do, not who may open it.)
    * **There is no ``stopped`` branch.** A preview has two states, running and
      gone, and "gone" is ``not_found``.

    The identity material is the ordinary one — this really is the approver
    visiting — plus the app id of the application under review, so the trial
    instance sees the same environment shape it will see in production.
    """
    if not settings.app_runtime.enabled:
        return {"decision": DECISION_NOT_ENABLED}

    subject = _decode_jwt_subject(access_token) if access_token else None
    if subject is None:
        return {"decision": DECISION_LOGIN, "reason": "no_session"}

    user_id = int(subject.get("user_id") or 0)
    tenant_id = int(subject.get("tenant_id") or 0)
    if not user_id:
        return {"decision": DECISION_LOGIN, "reason": "no_session"}

    session_reason = await _session_invalid_reason(user_id, tenant_id, subject, access_token)
    if session_reason:
        return {"decision": DECISION_LOGIN, "reason": session_reason}

    row = await _resolve_preview_session(session)
    if row is None:
        return {"decision": DECISION_NOT_FOUND}

    if int(row.approver_user_id or 0) != user_id:
        # Not ``forbidden``: the visitor has not been told this preview exists,
        # and telling them now — with an app name and an owner to ask — would
        # hand out the existence of an unpublished application (AC-30).
        logger.info(
            "app_runtime.preview_entry refused session={} visitor={} owner_of_session={}",
            session,
            user_id,
            row.approver_user_id,
        )
        return {"decision": DECISION_NOT_FOUND}

    app = await _load_app_by_id(str(row.app_id))
    if app is None:
        return {"decision": DECISION_NOT_FOUND}

    set_current_tenant_id(int(app.tenant_id or 0))
    user_name, subject_kind = await _user_facts(user_id, subject)
    material = await _identity_material(
        app=app, user_id=user_id, user_name=user_name, subject_kind=subject_kind, request_id=request_id
    )
    obo_token, obo_expires_at = _issue_obo_token(
        app_id=app.id,
        user_id=user_id,
        tenant_id=int(app.tenant_id or 0),
        subject_kind=material.get("X-BiSheng-Subject-Kind", "human"),
        # The approval exception rides the token, not a header: AC-27 widens
        # what the *platform* does for this visit, so the fact belongs where the
        # platform reads it back, never where the application could read — or
        # forge — it.
        preview_session=row.id,
    )
    if obo_token:
        material["X-BiSheng-Access-Token"] = obo_token
    logger.debug("app_runtime.preview_entry allow session={} user={} ip={}", session, user_id, client_ip)
    # No access record: AC-38 counts visits to an *application*, and a trial
    # instance of a version that may never ship is not one. Counting it would
    # inflate an app's usage with its own approvals.
    return {
        "decision": DECISION_ALLOW,
        "app_id": app.id,
        "app_name": app.name,
        "app_state": app.state,
        "preview_session": row.id,
        "headers": material,
        "obo_token": obo_token,
        "obo_expires_at": obo_expires_at,
        "ws_max_lifetime_seconds": int(settings.app_runtime.ws_max_lifetime_seconds),
    }


async def _resolve_preview_session(session: str):
    """F055 owns the session's lifetime; this module only asks whether it is live.

    Imported inside the function so ``app_runtime`` keeps no import-time edge to
    ``app_publish`` — the dependency direction is F055 → F054 everywhere else,
    and a module-level import here would make it a cycle.
    """
    try:
        from bisheng.app_publish.domain.services.preview_instance_service import PreviewInstanceService

        return await PreviewInstanceService.resolve_entry(session)
    except Exception as exc:
        # Fail-closed, like every other unanswerable question on this path
        # (AC-12): a broken lookup must not become "let them in".
        logger.error("app_runtime.preview_entry session lookup failed session={}: {}", session, exc)
        return None


async def _load_app_by_id(app_id: str) -> App | None:
    if not app_id:
        return None
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            row = await AppDao.aget(session, app_id)
    if row is None or row.state == AppState.DELETED.value:
        return None
    return row


# ---------------------------------------------------------------------------
# session
# ---------------------------------------------------------------------------


async def _session_invalid_reason(user_id: int, tenant_id: int, subject: dict, access_token: str) -> str | None:
    """The session checks the HTTP middleware performs and a local JWT decode does not.

    Same order and same helpers as ``CustomMiddleware``, so a session the platform
    has already signed out cannot keep opening hosted apps — in particular the
    single-login policy: with ``allow_multi_login`` off, a JWT that is no longer the
    user's current session is refused here exactly as it is on ``/api/v1``.
    """
    if not await _validate_token_version(user_id, int(subject.get("token_version", 0) or 0)):
        return "token_version_mismatch"
    if not await _validate_current_session_token(user_id, access_token):
        return "session_superseded"
    if await _account_disabled(user_id):
        return "account_disabled"
    if tenant_id and await _tenant_disabled(tenant_id):
        return "tenant_disabled"
    return None


async def _account_disabled(user_id: int) -> bool:
    from bisheng.user.domain.models.user import UserDao

    try:
        row = await UserDao.aget_user(user_id)
    except Exception as exc:
        logger.warning("app_runtime.entry account lookup failed user={}: {}", user_id, exc)
        return False
    return row is not None and int(row.delete or 0) == 1


async def _tenant_disabled(tenant_id: int) -> bool:
    """Redis blacklist, same key the middleware reads.

    Fails **open** on an unreachable Redis, deliberately matching
    ``CustomMiddleware``: the platform as a whole already behaves that way, and
    an entry path that fails closed here would lock every hosted application
    out during a cache blip while the rest of the product kept working.
    """
    try:
        from bisheng.core.cache.redis_manager import get_redis_client
        from bisheng.tenant.domain.services.tenant_service import DISABLED_TENANT_KEY

        client = await get_redis_client()
        return bool(await client.aget(DISABLED_TENANT_KEY.format(tenant_id)))
    except Exception as exc:
        logger.debug("app_runtime.entry tenant blacklist unavailable tenant={}: {}", tenant_id, exc)
        return False


async def _build_actor(user_id: int, subject: dict):
    from bisheng.common.dependencies.user_deps import UserPayload

    is_super = False
    try:
        is_super = await _check_is_global_super(user_id)
    except Exception as exc:
        logger.debug("app_runtime.entry super-admin probe failed user={}: {}", user_id, exc)
    return UserPayload(
        user_id=user_id,
        user_name=str(subject.get("user_name") or ""),
        user_role=[],
        tenant_id=int(subject.get("tenant_id") or 0),
        is_global_super=is_super,
    )


# ---------------------------------------------------------------------------
# app + identity material
# ---------------------------------------------------------------------------


async def _load_app_by_slug(slug: str) -> App | None:
    # The slug is global and the visitor's tenant context is not established
    # yet, so the lookup runs under bypass and the row's own tenant_id becomes
    # the authoritative tenant for everything after it.
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            return await AppDao.aget_by_slug(session, slug)


async def _owner_name(app: App) -> str | None:
    from bisheng.user.domain.models.user import UserDao

    try:
        row = await UserDao.aget_user(int(app.owner_user_id or 0))
    except Exception as exc:
        logger.debug("app_runtime.entry owner lookup failed app={}: {}", app.id, exc)
        return None
    return row.user_name if row is not None else None


async def _identity_material(
    *, app: App, user_id: int, user_name: str, subject_kind: str, request_id: str
) -> dict[str, str]:
    """The header values app-proxy will inject (AC-31).

    ``Dept-Id`` is the **business key** (``BS@xxx``), not the autoincrement id:
    the autoincrement one is meaningless outside the platform database and would
    make every hosted app's authorisation logic depend on a surrogate key.

    ``user_name`` / ``subject_kind`` come from :func:`_user_facts`, resolved by
    the caller once — the access record (AC-38) needs the plain name too, and
    reading it back out of the percent-encoded header would be a round trip
    that mangles an ASCII name containing a literal ``%``.
    """
    dept_id, dept_name, dept_path = await _primary_department(user_id)

    material: dict[str, str] = {
        "X-BiSheng-User-Id": str(user_id),
        "X-BiSheng-User-Name": _encode(user_name),
        "X-BiSheng-Tenant-Id": str(int(app.tenant_id or 0)),
        "X-BiSheng-Subject-Kind": subject_kind,
        "X-BiSheng-App-Id": app.id,
    }
    if request_id:
        material["X-BiSheng-Request-Id"] = request_id
    if dept_id:
        material["X-BiSheng-Dept-Id"] = dept_id
        material["X-BiSheng-Dept-Name"] = _encode(dept_name)
        material["X-BiSheng-Dept-Path"] = _encode(dept_path)
    return material


async def _user_facts(user_id: int, subject: dict) -> tuple[str, str]:
    """The visitor's display name plus the constant subject kind ``human``.

    A platform session belongs to a natural person by construction: service
    accounts are not rows of ``user`` (F053 design K15 / K17) and reach the
    platform only through ``/api/v2`` keys, never through ``/apps/{slug}``.
    The kind is still emitted so app-proxy's ``X-BiSheng-Subject-Kind`` (AC-31)
    keeps one authoritative writer.
    """
    from bisheng.user.domain.models.user import UserDao

    name = str(subject.get("user_name") or "")
    kind = "human"
    try:
        row = await UserDao.aget_user(user_id)
    except Exception as exc:
        logger.debug("app_runtime.entry user lookup failed user={}: {}", user_id, exc)
        return name, kind
    if row is not None:
        name = row.user_name or name
    return name, kind


async def _primary_department(user_id: int) -> tuple[str, str, str]:
    from bisheng.database.models.department import DepartmentDao, UserDepartmentDao

    try:
        # ``user_department`` has no tenant_id while ``department`` does, so the
        # pair is read under bypass and scoped by the user id instead.
        with bypass_tenant_filter():
            membership = await UserDepartmentDao.aget_user_primary_department(user_id)
            if membership is None:
                return "", "", ""
            department = await DepartmentDao.aget_by_id(int(membership.department_id))
    except Exception as exc:
        logger.debug("app_runtime.entry department lookup failed user={}: {}", user_id, exc)
        return "", "", ""
    if department is None:
        return "", "", ""
    return str(department.dept_id or ""), str(department.name or ""), str(department.path or "")


def _encode(value: str) -> str:
    """UTF-8 percent-encoding, idempotent for values that are already ASCII.

    HTTP headers are latin-1: a raw Chinese name is either rejected by h11 or
    arrives mangled. ``safe="/"`` keeps a department path readable.
    """
    text = str(value or "")
    return text if text.isascii() else quote(text, safe="/")


# ---------------------------------------------------------------------------
# OBO token
# ---------------------------------------------------------------------------


#: Config problems already reported. Keyed by cause, not by message, so a
#: reworded log line does not start flooding again.
_WARNED_ONCE: set[str] = set()


def _warn_once(key: str, message: str) -> None:
    if key in _WARNED_ONCE:
        return
    _WARNED_ONCE.add(key)
    logger.error(message)


def _issue_obo_token(
    *,
    app_id: str,
    user_id: int,
    tenant_id: int,
    subject_kind: str,
    preview_session: str | None = None,
) -> tuple[str | None, int | None]:
    """Short-lived on-behalf-of token injected into the app (AC-34).

    ``preview_session`` marks the token as belonging to an **approval-time
    trial**, and it is the carrier for the one exception in NFR-1.2 / INV-36:
    inside a preview the platform capabilities pass at the **owner's** level
    (F055 AC-27) rather than at the visitor's, because the point of the trial is
    to see the release work, and an approver who is not in the app's knowledge
    scope would otherwise see a release that "does not work". The flag has to
    ride the token: it is the only thing the capability bus gets that says
    *which* visit this is, and a capability bus that cannot tell a preview from
    a production visit will quietly apply the wrong rule to both. No reader
    yet — the capability bus is F055 T056 to T060 — so this is the fact being
    carried, not the rule being applied.

    Returns ``(token, expires_at)`` — the expiry as epoch seconds, so the
    caller can state it to app-proxy without decoding the token — or
    ``(None, None)`` when no token is issued.

    Signed with ``app_runtime.obo_secret``, which **must differ** from
    ``settings.jwt_secret``: sharing them would make every OBO token a valid
    platform session cookie. A missing or shared secret means no token is
    issued — the token has no consumer this round (its scope semantics belong
    to F055), so refusing entry over it would break the entry path to protect
    something nobody reads yet.

    ⚠️ **When OBO gains its first consumer this must become fail-closed.** The
    day an application reads the token to decide who it is talking to, "no
    token issued" stops meaning "nobody reads it" and starts meaning "the app
    sees an anonymous request" — a silent fail-open on identity. Ruled
    2026-08-17: allow this round, flip to refusing entry in the same change
    that gives OBO a reader.

    Both misconfigurations are logged **once per process, not per request**:
    they are static config, they never heal on their own, and a per-request
    line on every entry both floods the log and buries the one occurrence that
    would have told an operator what to fix.
    """
    secret = settings.app_runtime.obo_secret
    if not secret:
        _warn_once("obo_secret_missing", "app_runtime.entry obo_secret is not configured; no OBO token issued")
        return None, None
    if secret == settings.jwt_secret:
        _warn_once(
            "obo_secret_equals_jwt",
            "app_runtime.entry obo_secret equals jwt_secret; refusing to sign (AC-34). "
            "Sharing them would make every OBO token a valid platform session — set a distinct secret.",
        )
        return None, None

    now = int(time.time())
    expires_at = now + int(settings.app_runtime.obo_ttl_seconds)
    subject: dict[str, Any] = {
        "app_id": app_id,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "subject_kind": subject_kind,
    }
    if preview_session:
        subject["preview_session"] = preview_session
    payload = {
        # Serialised like the platform's own session subject so both decode the
        # same way; PyJWT 2.10 also requires ``sub`` to be a string.
        "sub": json.dumps(subject, sort_keys=True),
        "aud": OBO_AUDIENCE,
        "iss": settings.cookie_conf.jwt_iss,
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(payload, secret, algorithm="HS256"), expires_at
