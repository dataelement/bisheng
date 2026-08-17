"""App-factory error codes — module 161 (F054 design §4.2 ⑥ / K11).

Module 161 is the F054 slice of the app-factory band; F055 owns 162, F056 163
and F059 164. 161 was verified free before it was claimed (the 16x band held
only 160 = dataset), and 260 is **taken** by F049 open API auth — do not treat
either as spare.

Sub-ranges (design §4.2 ⑥):

* ``16100-16119`` domain / state machine
* ``16120-16139`` runtime / orchestration
* ``16140-16159`` entry & identity injection
* ``16160-16179`` data plane / logs
* ``16180-16199`` deployment switch / ops

Two constraints that are easy to miss:

* **Never return 403/404 to the platform SPA for an "app I may not see"
  answer.** The platform request interceptor turns a GET with HTTP 403 / 404
  into a full-page redirect to ``/403`` / ``/404`` (design pit 25), so the
  detail page and the log tab must answer with these business codes inside a
  200 envelope instead.
* Copy for every code lives in
  ``src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json`` and
  ships in the same change (CI ``pnpm check-i18n``). The generated artifacts
  under ``platform/public/locales`` / ``client/src/locales`` are never edited
  by hand.
"""

from bisheng.common.errcode.base import BaseErrorCode


class AppFactoryError(BaseErrorCode):
    """Base of the 161xx family (hosted application domain + runtime)."""

    Code: int = 16100
    Msg: str = "App factory error"


# ---------------------------------------------------------------------------
# 16100-16119 — domain / state machine
# ---------------------------------------------------------------------------


class AppNotFoundError(AppFactoryError):
    """No such application, or it is deleted / invisible to the caller.

    Deliberately the same answer for "does not exist" and "exists but you may
    not know that": the entry path treats draft / pending / deleted / unknown
    alike (AC-29).
    """

    Code: int = 16101
    Msg: str = "Application does not exist"


class AppStateConflictError(AppFactoryError):
    """A state action ran against an unexpected prior state.

    Raised when the compare-and-set UPDATE in ``AppDao.aupdate_state_cas``
    matches zero rows — i.e. a concurrent action already moved the app, or the
    transition is not in ``ALLOWED_TRANSITIONS``.
    """

    Code: int = 16102
    Msg: str = "Application state conflict: the current state does not allow this action"


class AppSlugConflictError(AppFactoryError):
    """``slug`` is unique across **all** tenants — it is the public entry segment."""

    Code: int = 16103
    Msg: str = "Application identifier is already taken"


class AppOnlineCannotDeleteError(AppFactoryError):
    """Deleting an online app is blocked; stop it first (AC-42)."""

    Code: int = 16104
    Msg: str = "An online application cannot be deleted; stop it first"


class AppOwnerOnlyError(AppFactoryError):
    """Owner-only action (delete / data tab).

    A **business** pre-check, not a permission-runtime verdict: tenant
    administrators are short-circuited to allow by the permission runtime, so
    "owner only" can never be expressed as an FGA check (constitution C4 note /
    design §2).
    """

    Code: int = 16105
    Msg: str = "Only the application owner may perform this action"


class AppManageForbiddenError(AppFactoryError):
    """Management action reserved to the owner, a tenant administrator or a super admin.

    Kept apart from :class:`AppOwnerOnlyError` because the two answer different
    questions and the copy differs accordingly: 16105 means "**only** the owner"
    (delete, the data tab — a tenant admin is refused there too), 16106 means
    "you are none of the three". Folding them together would tell a tenant
    administrator who just stopped an app that only its owner may do so.
    """

    Code: int = 16106
    Msg: str = "Only the application owner or an administrator may perform this action"


# ---------------------------------------------------------------------------
# 16120-16139 — runtime / orchestration
# ---------------------------------------------------------------------------


class AppOrchestratorUnavailableError(AppFactoryError):
    """runtime-manager unreachable, or its orchestration backend is down."""

    Code: int = 16121
    Msg: str = "The application runtime is unavailable"


class AppBuildFailedError(AppFactoryError):
    """Build failed; ``data`` carries ``stage`` / ``message`` / ``tail`` (AC-15)."""

    Code: int = 16122
    Msg: str = "Application build failed"


class AppRuntimeNotSupportedError(AppFactoryError):
    """``runtime`` is not among the templates this deployment actually ships.

    The supported set is reported by runtime-manager (``GET /v1/runtime/status``),
    not hardcoded here — MVP ships ``python3.11`` only.
    """

    Code: int = 16123
    Msg: str = "Unsupported runtime"


class AppProbeFailedError(AppFactoryError):
    """The instance started but never became ready within the probe budget (AC-18)."""

    Code: int = 16124
    Msg: str = "The application failed to start: readiness probe did not pass"


class AppCapacityInsufficientError(AppFactoryError):
    """Capacity admission rejected the request (AC-19 / AC-65).

    Applies to builds as well as starts — a build that is admitted "because it
    is only a build" is exactly how 114 ran out of memory (design K2).
    """

    Code: int = 16125
    Msg: str = "Insufficient runtime capacity"


# ---------------------------------------------------------------------------
# 16140-16159 — entry & identity injection
# ---------------------------------------------------------------------------


class AppEntryLoginRequiredError(AppFactoryError):
    """No platform session on the entry path — hand off to the login page (AC-27)."""

    Code: int = 16141
    Msg: str = "Sign in to open this application"


class AppEntryForbiddenError(AppFactoryError):
    """Signed in, but outside the application's visible scope (AC-28)."""

    Code: int = 16142
    Msg: str = "You do not have access to this application"


class AppEntryStoppedError(AppFactoryError):
    """The application is stopped — shown only to users inside its visible scope (AC-29)."""

    Code: int = 16143
    Msg: str = "This application is currently stopped"


class AppEntryNotOnlineError(AppFactoryError):
    """Draft / pending / deleted / unknown all collapse into this one answer (AC-29)."""

    Code: int = 16144
    Msg: str = "This application does not exist or is not online"


class AppFactoryNotEnabledError(AppFactoryError):
    """The app factory switch is off for this deployment (AC-30 / AC-62)."""

    Code: int = 16145
    Msg: str = "The app factory is not enabled in this environment"


class AppPermissionEngineUnavailableError(AppFactoryError):
    """The permission engine could not answer — **deny**, never pass through (AC-12).

    Mapped from ``PermissionServiceUnavailableError`` /
    ``PermissionBackendUnavailableError``; fail-closed is the whole point.
    """

    Code: int = 16146
    Msg: str = "The permission service is unavailable; access is denied"


# ---------------------------------------------------------------------------
# 16160-16179 — data plane / logs
# ---------------------------------------------------------------------------


class AppLogForbiddenError(AppFactoryError):
    """Log tab is visible to the owner or a tenant administrator (AC-55)."""

    Code: int = 16161
    Msg: str = "You do not have permission to view this application's logs"


# ``16162`` (no permission to access application data, AC-56) is reserved for
# the deferred data-tab wave. Declare it there, not here.


# ---------------------------------------------------------------------------
# 16180-16199 — deployment switch / ops
# ---------------------------------------------------------------------------


class AppRuntimeLayerNotDeployedError(AppFactoryError):
    """The runtime layer (runtime-manager / app-proxy) is not deployed here.

    Distinct from :class:`AppFactoryNotEnabledError`: 16145 answers the *entry*
    path ("this environment has the factory switched off"), 16181 answers the
    *management* surfaces ("the switch is on but the runtime processes are not
    installed"), which is what makes AC-59..AC-62 separable.
    """

    Code: int = 16181
    Msg: str = "The app factory runtime layer is not deployed in this environment"
