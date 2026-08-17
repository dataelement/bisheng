"""Publish-pipeline error codes — module 162 (F055 design §4.2 ⑧ / K9).

Module 162 is the F055 slice of the app-factory band: **161 = F054**
(hosted-app domain + runtime, ``app_factory.py``) · **162 = F055** (this file)
· 163 = F056 · 164 = F059. The assignment is already written into
``docs/constitution.md`` C5 and ``features/v3.0.0/release-contract.md`` — do
not "correct" those tables, and do not add F055 codes to ``app_factory.py``.

Sub-ranges (design §4.2 ⑧):

* ``16200-16219`` receive & package
* ``16220-16239`` precheck
* ``16240-16249`` secret scan
* ``16250-16269`` publish flow
* ``16270-16289`` capability bus
* ``16290-16299`` runtime credentials

One code, one meaning (C5) — the three traps this family has already fallen
into once, keep them in mind before adding a code:

* **``16225`` is only "the approval scenario is not seeded".** Capacity
  shortage during build or start is **``16226``**. The CLI's remedy differs
  completely ("ask an administrator to seed the scenario" vs. "the machine is
  out of memory, retry later or publish manually"), so merging them guarantees
  one of the two copy strings is wrong wherever it is shown.
* **A tier failure is only ever ``16223``.** "Does not exist" and "is
  disabled" are the same code with ``details.reason ∈ {not_found, disabled}``;
  splitting them into two codes was tried and produced a code with no writer.
* **``withdraw`` terminal-state guarding belongs to the approval band
  (181xx)**, not here (design D10).

Copy for every code lives in
``src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json`` and ships
in the same change (CI ``pnpm check-i18n``). The generated artifacts under
``platform/public/locales`` / ``client/src/locales`` are never hand-edited.

Two codes are declared here before their first writer exists — ``16273`` /
``16274`` (capability bus, deferred wave). That is deliberate: the whitelist,
the three locale files and this module are one lockstep, and touching all four
twice for the same feature is how a code ends up written but untranslated.
"""

from bisheng.common.errcode.base import BaseErrorCode


class AppPublishError(BaseErrorCode):
    """Base of the 162xx family (publish pipeline, approval, version records, tiers)."""

    Code: int = 16200
    Msg: str = "App publish error"


# ---------------------------------------------------------------------------
# 16200-16219 — receive & package
# ---------------------------------------------------------------------------


class AppPackageTooLargeError(AppPublishError):
    """Upload exceeded ``settings.app_runtime.max_package_mb`` / ``max_unpacked_mb`` / ``max_package_entries``.

    One code for all three gates: the CLI's remedy is identical ("your package
    is too big — check .gitignore"), and ``data`` carries which gate tripped and
    the actual figure so the message can name it.
    """

    Code: int = 16201
    Msg: str = "The application package exceeds the size limit of this deployment"


class AppPackageInvalidError(AppPublishError):
    """The tarball could not be unpacked, or it carries an entry that must never be extracted.

    Absolute paths, ``..`` traversal, symlinks, hardlinks, device files and
    FIFOs all land here — a tar has four more dangerous entry kinds than a zip
    (design pit 15), and the caller is told which one without any hint that
    another kind might have been allowed.
    """

    Code: int = 16202
    Msg: str = "The application package could not be parsed, or contains an illegal entry"


class AppManifestMissingError(AppPublishError):
    """No ``bisheng-app.yaml`` at the package root."""

    Code: int = 16203
    Msg: str = "bisheng-app.yaml is missing from the package root"


class AppNotOwnedBySubjectError(AppPublishError):
    """The target app belongs to somebody else than the credential's resource owner (AC-04).

    A **business** pre-check, not a permission verdict: ``app:manage`` says the
    key may publish, the resource owner says *whose* apps it may publish.
    """

    Code: int = 16205
    Msg: str = "This application belongs to another owner"


class AppPublishRuntimeLayerDisabledError(AppPublishError):
    """``settings.app_runtime.enabled`` is off — the pipeline has nothing to publish onto.

    Distinct from F054's 16181: that one answers the management surfaces, this
    one answers ``/api/v2/apps/deploy`` so the CLI can say "this environment
    does not run the app factory" instead of timing out on a build.
    """

    Code: int = 16207
    Msg: str = "The app factory runtime layer is not enabled in this environment"


# ---------------------------------------------------------------------------
# 16220-16239 — precheck
# ---------------------------------------------------------------------------


class AppManifestInvalidError(AppPublishError):
    """``bisheng-app.yaml`` failed schema validation (AC-07 / AC-11).

    ``data`` carries the five-tuple ``{stage, code, message, details, hints}``;
    ``details`` is the pydantic ``{loc, msg, type}`` list turned into
    ``{field, reason}`` so the CLI can point at the offending line.
    """

    Code: int = 16221
    Msg: str = "bisheng-app.yaml failed validation"


class AppRuntimeUnsupportedError(AppPublishError):
    """``runtime`` is not one of the templates this deployment ships.

    The manifest schema holds a local copy of the supported set for the
    synchronous leg (no RPC in the receive path); runtime-manager's own list is
    re-checked in the asynchronous leg. Both raise this.
    """

    Code: int = 16222
    Msg: str = "Unsupported runtime"


class AppTierUnavailableError(AppPublishError):
    """The declared ``tier`` does not exist or has been disabled (AC-46 / AC-47).

    **One code, two reasons.** ``data.reason`` is ``"not_found"`` or
    ``"disabled"``; do not split this into two codes (see the module
    docstring).
    """

    Code: int = 16223
    Msg: str = "The declared resource tier does not exist or has been disabled"


class AppCapabilityUnresolvableError(AppPublishError):
    """A declared model / knowledge base cannot be resolved to an existing resource."""

    Code: int = 16224
    Msg: str = "A declared capability could not be resolved"


class AppApprovalScenarioDisabledError(AppPublishError):
    """The ``app_publish_request`` approval scenario is not seeded / is switched off.

    **Only** this. Capacity shortage is 16226 — see the module docstring.
    Raised by the approval gate before any version row is inserted (design D6),
    so a deployment that hits it leaves no zombie version behind.
    """

    Code: int = 16225
    Msg: str = "The application publish approval scenario is not enabled in this environment"


class AppCapacityInsufficientError(AppPublishError):
    """The capacity admission gate rejected the build or the start.

    F054's 16125 is the same condition seen from a state action; this one is
    the pipeline's own, so the CLI can distinguish "your publish parked" from
    "somebody's manual start was refused".
    """

    Code: int = 16226
    Msg: str = "Insufficient runtime capacity"


class AppDependencyBuildFailedError(AppPublishError):
    """Dependency installation / image build failed; ``data`` carries the log tail."""

    Code: int = 16227
    Msg: str = "Dependency installation failed while building the application"


class AppStartupProbeFailedError(AppPublishError):
    """The application built but never became ready within the probe budget."""

    Code: int = 16228
    Msg: str = "The application failed to start: readiness probe did not pass"


class AppSchemaChangeUnconfirmedError(AppPublishError):
    """A breaking table-structure change was detected without ``confirm_schema_change`` (deferred wave)."""

    Code: int = 16229
    Msg: str = "The table structure change must be confirmed explicitly"


class AppSecretReferenceUnsupportedError(AppPublishError):
    """The capability declaration references a secret; this version does not support that (AC-56)."""

    Code: int = 16230
    Msg: str = "Secret references in the capability declaration are not supported in this version"


class AppCapabilityBusDisabledError(AppPublishError):
    """A non-empty ``capabilities`` block on a deployment without the capability bus.

    Rejected rather than silently ignored (design D16): quietly dropping the
    declaration would leave the app running without the models it asked for and
    no way for the owner to find out.
    """

    Code: int = 16231
    Msg: str = "The capability bus is not enabled in this environment; remove the capabilities declaration"


# ---------------------------------------------------------------------------
# 16240-16249 — secret scan
# ---------------------------------------------------------------------------


class AppSecretScanBlockedError(AppPublishError):
    """The pre-publish secret scan matched (AC-10).

    ``data.hits`` is ``[{rule_id, name_i18n_key, file, line}]`` — file and line
    only. **The matched value never leaves the scanner**, not even masked.
    """

    Code: int = 16241
    Msg: str = "The pre-publish secret scan found credentials in the package"


# ---------------------------------------------------------------------------
# 16250-16269 — publish flow
# ---------------------------------------------------------------------------


class AppApprovalInFlightError(AppPublishError):
    """This app already has a publish request under approval (AC-03).

    Checked by the caller **before** the approval gate: the gate silently
    returns the existing instance for a duplicate submission
    (``find_duplicate_active_instance``), which would make a second ``deploy``
    look like it succeeded (design K2 ①).
    """

    Code: int = 16251
    Msg: str = "This application already has a publish request under approval"


class AppPendingOnlineError(AppPublishError):
    """The app is parked in "pending online"; a new submission is refused until it is resolved (AC-31)."""

    Code: int = 16252
    Msg: str = "This application is waiting to go online; resolve that first"


class AppVersionNotFoundError(AppPublishError):
    """No such version record for this app."""

    Code: int = 16253
    Msg: str = "The version record does not exist"


class AppPublishOwnerOnlyError(AppPublishError):
    """Withdraw / manual publish / retry are owner-only actions."""

    Code: int = 16254
    Msg: str = "Only the application owner may perform this action"


class AppPublishStateConflictError(AppPublishError):
    """The application's current state does not allow this publish action."""

    Code: int = 16255
    Msg: str = "The current application state does not allow this action"


# ---------------------------------------------------------------------------
# 16270-16289 — capability bus (deferred wave; registered once, see docstring)
# ---------------------------------------------------------------------------


class AppCapabilityRevokedError(AppPublishError):
    """The capability was granted at approval time and has since been revoked (AC-63)."""

    Code: int = 16273
    Msg: str = "This capability has been revoked"


class AppCapabilityNotDeclaredError(AppPublishError):
    """The application asked for a capability it never declared (AC-49)."""

    Code: int = 16274
    Msg: str = "This capability was not declared by the application"


# ---------------------------------------------------------------------------
# 16290-16299 — runtime credentials (deferred wave)
# ---------------------------------------------------------------------------


class AppRuntimeSubjectUnavailableError(AppPublishError):
    """The application's runtime credential subject is disabled or missing (AC-57)."""

    Code: int = 16291
    Msg: str = "The application runtime credential subject is unavailable"
