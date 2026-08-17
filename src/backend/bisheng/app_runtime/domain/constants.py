"""Shared F054 constants: application state machine, audit actions, factory tiers.

Everything here is a value — no I/O, no DB, no imports from services. Three
groups, each the single source of truth for its concept:

* :class:`AppState` + :data:`ALLOWED_TRANSITIONS` — the whole state machine
  (AC-03). ``AppStateService`` is the only writer of ``app.state`` (决议-8) and
  it validates against this table before issuing the compare-and-set UPDATE.
* :class:`AppAuditAction` — every ``audit_log.action`` string this feature
  emits. Registering a member here is the code-level half of the lockstep with
  ``_UI_VISIBLE_V2_ACTIONS`` and the platform log filter (design pit 24);
  writing an unregistered action means the row lands in the DB and never shows
  up on the "系统操作" page.
* :data:`DEFAULT_TIERS` — the factory specs of the three resource tiers, and
  the **only** code-level source of them. F055's ``ResourceTier`` seed reads
  this table when it populates the DB, which is what makes "table not seeded
  yet" and "table just seeded" produce identical limits (design D11).

State-machine facts that are not obvious from the names:

* ``pending_capacity`` ("待上线·资源不足") is a real state, not a UI label: an
  app that passed approval but lost the capacity gate sits here and is retried
  by an explicit action, never auto-promoted (AC-19 / AC-65).
* **online → deleted is forbidden.** Deleting a running app has to go through
  stop first (AC-42), so that the container and its host volume are always torn
  down by a state action rather than orphaned by a row disappearing.
* ``deleted`` is terminal: the row stays for audit, and nothing transitions out
  of it.
"""

from __future__ import annotations

from enum import StrEnum


class AppState(StrEnum):
    """The five application states (AC-03). ``app.state`` stores the value."""

    DRAFT = "draft"
    ONLINE = "online"
    #: Approved but not running: capacity admission rejected the start (AC-19).
    PENDING_CAPACITY = "pending_capacity"
    STOPPED = "stopped"
    DELETED = "deleted"


#: Legal transitions, keyed by source state (AC-03).
#:
#: Read it as "from → allowed targets". The absence of
#: ``ONLINE → DELETED`` is deliberate and load-bearing — see the module
#: docstring.
ALLOWED_TRANSITIONS: dict[AppState, frozenset[AppState]] = {
    AppState.DRAFT: frozenset({AppState.ONLINE, AppState.PENDING_CAPACITY, AppState.DELETED}),
    AppState.ONLINE: frozenset({AppState.STOPPED}),
    AppState.PENDING_CAPACITY: frozenset({AppState.ONLINE, AppState.DELETED}),
    AppState.STOPPED: frozenset({AppState.ONLINE, AppState.PENDING_CAPACITY, AppState.DELETED}),
    AppState.DELETED: frozenset(),
}

#: States whose apps may be reached through the public entry (AC-29). Draft /
#: pending / deleted / unknown all answer "does not exist or is not online".
ENTRY_VISIBLE_STATES: frozenset[AppState] = frozenset({AppState.ONLINE, AppState.STOPPED})


def is_transition_allowed(source: str, target: str) -> bool:
    """Whether ``source → target`` is in the table; unknown states are never allowed."""
    try:
        return AppState(target) in ALLOWED_TRANSITIONS[AppState(source)]
    except (KeyError, ValueError):
        return False


def allowed_sources(target: str) -> tuple[str, ...]:
    """States that may transition into ``target`` — the ``WHERE state IN (...)`` of the CAS UPDATE."""
    try:
        goal = AppState(target)
    except ValueError:
        return ()
    return tuple(source.value for source, targets in ALLOWED_TRANSITIONS.items() if goal in targets)


class AppAuditAction(StrEnum):
    """``audit_log.action`` values owned by F054 (namespace ``app.``).

    Registered in lockstep with ``database/models/audit_log.py``
    ``_UI_VISIBLE_V2_ACTIONS`` / ``_V2_NAMESPACE_TO_ACTION_PREFIX`` and the
    platform ``controllers/API/log.ts`` filter — adding a member here without
    the other side means the event is written but invisible (pit 24).
    """

    PUBLISH = "app.publish"
    #: Publish attempt that hit the capacity gate and parked in pending_capacity.
    PUBLISH_PENDING = "app.publish_pending"
    MANUAL_PUBLISH = "app.manual_publish"
    STOP = "app.stop"
    RESUME = "app.resume"
    DELETE = "app.delete"
    #: A deletion hook (e.g. F055 cancelling an in-flight approval) failed; the
    #: deletion itself already happened, so this is recorded rather than raised.
    DELETE_HOOK_FAILED = "app.delete_hook_failed"
    META_UPDATE = "app.meta_update"
    #: Data-tab row edit (AC-56) — deferred wave, registered now so the audit
    #: whitelist is touched exactly once.
    DATA_ROW_EDIT = "app.data_row_edit"


#: Factory resource tiers (GOV-03). ``cpu`` is in vCPU, ``memory_mb`` in MiB.
#:
#: The single code-level source of the three tiers: F055 seeds its
#: ``ResourceTier`` rows from here, so an un-seeded deployment and a freshly
#: seeded one resolve the same limits. Once the table exists it wins — a super
#: admin may retune the specs (AC-64), and running instances keep the limits
#: frozen into them at create time (AC-63).
DEFAULT_TIERS: tuple[dict[str, object], ...] = (
    {"tier_id": "light", "name": "轻量", "cpu": 0.5, "memory_mb": 512},
    {"tier_id": "standard", "name": "标准", "cpu": 1.0, "memory_mb": 1024},
    {"tier_id": "enhanced", "name": "增强", "cpu": 2.0, "memory_mb": 2048},
)

DEFAULT_TIER_ID = "standard"


def default_tier(tier_id: str) -> dict[str, object] | None:
    """Look up a factory tier spec, or ``None`` when the id is unknown."""
    for tier in DEFAULT_TIERS:
        if tier["tier_id"] == tier_id:
            return tier
    return None
