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

``16273`` / ``16274`` (capability bus) were registered one wave before their
first writer landed, so the whitelist, the three locale files and this module
were touched once rather than twice. Both are written now
(``app_publish/domain/services/capability_bus_service.py``).
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
    """A breaking table-structure change (drop / modify) was detected without ``confirm_schema_change`` (AC-09)."""

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


class AppWebSocketUnsupportedError(AppPublishError):
    """The manifest declares an inbound WebSocket endpoint, which this version's entry cannot carry.

    Its own code rather than a generic 16221 for exactly the reason 16230 is
    its own code: as an "unknown field" the developer is told to rename or
    delete the key, when the true answer is that **no** manifest spelling buys
    a WebSocket this version — ``app-proxy`` refuses the upgrade with close
    code ``4501`` (``login_handoff.WS_CLOSE_NOT_IMPLEMENTED``; the reverse
    proxy itself is F054 T079/T080).

    Refused rather than accepted-and-ignored for the same reason as 16231: the
    failure is otherwise invisible. nginx forwards ``Upgrade`` fine, so there
    is no 502 — the handshake is closed by the peer, the app's own JavaScript
    sees a ``close`` event, and the platform logs stay clean. An owner has
    nothing to debug with.
    """

    Code: int = 16232
    Msg: str = "WebSocket is not supported by the hosted runtime in this version"


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


class AppVersionSnapshotUnavailableError(AppPublishError):
    """The version row exists but its frozen package cannot be read (AC-25 / AC-41).

    Distinct from 16253: the *record* is there, the *bytes* are not — the
    object was swept, the bucket is unreachable, or the archive no longer
    parses. ``data.reason`` says which; the remedy is an administrator looking
    at object storage, never a resubmission.
    """

    Code: int = 16256
    Msg: str = "The code snapshot of this version is unavailable"


class AppVersionReviewForbiddenError(AppPublishError):
    """The caller may not read this version's source (AC-25 / AC-30).

    Owner, the app's tenant administrator, a platform super admin, or an
    approver who holds a task on the publish request of **that version** —
    nobody else. A dedicated code rather than 16254 because the copy of 16254
    ("owner only") is untrue for a page approvers are meant to open.

    Rides in the 200 envelope for the same reason every other read here does
    (design K11 ②).
    """

    Code: int = 16257
    Msg: str = "You do not have permission to view the source of this version"


class AppSnapshotFileNotFoundError(AppPublishError):
    """``path`` is not a regular file inside the snapshot.

    Covers a directory, a missing entry and an illegal path (absolute /
    traversal) alike — ``data.reason`` distinguishes them; the client only
    needs to know the file cannot be shown.
    """

    Code: int = 16258
    Msg: str = "The file does not exist in this version's snapshot"


# ---------------------------------------------------------------------------
class AppSchemaMigrationFailedError(AppPublishError):
    """The declared application tables could not be brought to their new shape (AC-42 / T062).

    Raised only at go-live, from the migration runtime-manager performs before
    the new version is started, and deliberately **not** merged into 16229:
    16229 is "you have not confirmed a breaking change", answered on the
    upload, and its remedy is ``--confirm-schema-change``. This one means the
    change was confirmed and the database would not take it — a NOT NULL column
    existing rows have no value for, a type name that is not a type name, a
    snapshot that could not be stored — and its remedy is a different
    ``bisheng-app.yaml``.

    ``details.reason`` carries the manager's verdict (``notnull_without_default``
    / ``invalid_type`` / ``invalid_identifier`` / ``invalid_plan`` /
    ``invalid_default`` / ``sqlite_error`` / ``snapshot_failed``) plus the
    ``table`` / ``column`` it is about, so the copy can name them. **A failed
    migration never starts the new version**: the release stops here and
    whatever was already serving keeps serving.
    """

    Code: int = 16259
    Msg: str = "Application data tables could not be migrated"


# 16260-16263 — the resource-tier admin surface (AC-45 / T065). These answer
# the super admin editing tiers on the system page; the manifest-side tier
# failure stays 16223 (a CLI author's typo or a retired tier), because the
# remedy there is "change your bisheng-app.yaml", not "refresh the admin list".


class AppTierAdminForbiddenError(AppPublishError):
    """Tier management is a platform super-admin surface (AC-45).

    A business code rather than an HTTP 403 on purpose: the platform's
    response interceptor navigates the whole SPA to ``/403`` on a real 403,
    and a tenant administrator who reaches the URL by hand should see a
    refusal, not lose the page.
    """

    Code: int = 16260
    Msg: str = "Only a platform super administrator may manage resource tiers"


class AppTierEditTargetNotFoundError(AppPublishError):
    """The tier being edited does not exist — the admin list is stale, refresh it."""

    Code: int = 16261
    Msg: str = "The resource tier to edit does not exist"


class AppTierSpecInvalidError(AppPublishError):
    """A tier patch failed validation (``data.field`` names the offender).

    CPU millicores and memory MB are positive integers, the name is non-empty
    and the description fits its column; ``code`` is never editable — renaming
    a tier would dangle every ``app_version.tier_id`` frozen against it.
    """

    Code: int = 16262
    Msg: str = "The resource tier specification is invalid"


class AppTierDefaultCannotBeDisabledError(AppPublishError):
    """The default tier (what a manifest without ``tier:`` resolves to) cannot be retired.

    Retiring it would make every ``bisheng deploy`` that never declared a tier
    fail 16223 with "light is disabled" — a platform-wide outage described as
    a per-manifest mistake. Retune it instead, or change which tier is the
    default in code.
    """

    Code: int = 16263
    Msg: str = "The default resource tier cannot be disabled"


# 16264-16267 — approval-time preview instances (AC-26～AC-29 / T053). They are
# their own little band because the approver's screen shows them next to the
# review view's 1625x codes and the two must not be confused: 1625x is about
# *reading* a version, 1626x is about *running* one.


class AppPreviewForbiddenError(AppPublishError):
    """The caller may not raise or reclaim a preview of this version (AC-26 / AC-30).

    The same rule as the review view (``ReviewAccess``) minus one branch: only
    people who can *decide* on this release get a running instance of it, so an
    approver holding a task on that version, the owner, the app's tenant
    administrator and a platform super admin — nobody else.

    Deliberately **not** 16257: that code's copy says "you cannot view the
    source", which is the wrong sentence on a button whose subject is a
    trial run, and both appear on the same screen.
    """

    Code: int = 16264
    Msg: str = "You do not have permission to run a preview of this version"


class AppPreviewNotRunnableError(AppPublishError):
    """This version has nothing to start a preview from (AC-26).

    Most often a release that never finished its build — ``image_ref`` is only
    written once the build stage succeeds — but also a version whose approval
    already ended, where a trial instance would be answering questions nobody
    is deciding on any more. ``data.reason`` says which.
    """

    Code: int = 16265
    Msg: str = "This version cannot be previewed"


class AppPreviewStartFailedError(AppPublishError):
    """The preview instance did not come up (AC-26 「拉起失败展示原因并允许重新拉起」).

    Carries the orchestrator's own reason: capacity, or a container that never
    became ready. The remedy is the same either way — look at the reason and
    press 「拉起预览」 again — which is why the two do not get separate codes
    here; the capacity case already has 16226 for the *publish* path, and
    reusing it would make a failed trial look like a failed release.
    """

    Code: int = 16266
    Msg: str = "The preview instance could not be started"


class AppPreviewSessionNotFoundError(AppPublishError):
    """No such preview session, or it has already been reclaimed.

    One answer for both, deliberately: a reclaimed session and a fabricated id
    must look the same to anyone poking at ``/apps/preview/{session}``.
    """

    Code: int = 16267
    Msg: str = "The preview session does not exist or has been reclaimed"


# ---------------------------------------------------------------------------
# 16270-16289 — capability bus
# ---------------------------------------------------------------------------
#
# Model refusals stay in the 262 band (``26212`` / ``26213`` offline / revoked,
# ``26215`` undeclared) — the two codes below are for knowledge and every later
# non-model capability. Two pairs is deliberate: a model refusal is rendered as
# an OpenAI error body on the model face, and translating it into a 162 code
# would strip that rendering (design D13).


class AppCapabilityRevokedError(AppPublishError):
    """A declared capability is gone from the platform since the release (AC-53 / AC-63).

    Carries the capability's **name as the owner wrote it** plus a machine
    reason, because "which of my six knowledge bases stopped working" is the
    only question the owner actually has. ``reason`` is the vocabulary the
    publish surface's 「已失效」 mark reads: ``revoked`` (gone or no longer of a
    retrievable type), ``ambiguous`` (a bare name that now matches several) and
    ``unresolvable`` (never resolved at all).
    """

    Code: int = 16273
    Msg: str = "能力「{capability}」已被收回"

    def __init__(
        self,
        capability: str | None = None,
        *,
        kind: str | None = None,
        reason: str = "revoked",
        knowledge_id: int | None = None,
        **kwargs,
    ):
        super().__init__(
            msg=self.Msg.format(capability=capability or ""),
            capability=capability,
            kind=kind,
            reason=reason,
            knowledge_id=knowledge_id,
            **kwargs,
        )
        self.capability = capability
        self.reason = reason


class AppCapabilityNotDeclaredError(AppPublishError):
    """The application asked for a capability it never declared (AC-51).

    Distinct from 16273 on purpose: the remedies differ completely — declare it
    and publish again, versus ask an administrator why it disappeared.
    """

    Code: int = 16274
    Msg: str = "能力「{capability}」未在应用的能力声明中"

    def __init__(self, capability: str | None = None, *, kind: str | None = None, **kwargs):
        super().__init__(
            msg=self.Msg.format(capability=capability or ""),
            capability=capability,
            kind=kind,
            **kwargs,
        )
        self.capability = capability


# ---------------------------------------------------------------------------
# 16290-16299 — runtime credentials (deferred wave)
# ---------------------------------------------------------------------------


class AppRuntimeSubjectUnavailableError(AppPublishError):
    """The application's runtime credential subject is disabled or missing (AC-57)."""

    Code: int = 16291
    Msg: str = "The application runtime credential subject is unavailable"
