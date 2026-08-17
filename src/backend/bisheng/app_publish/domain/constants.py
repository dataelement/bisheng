"""Shared F055 constants: the ``app.release.*`` audit action family.

Same shape and same purpose as F054's ``app_runtime/domain/constants.py``
``AppAuditAction``: a value-only module (no I/O, no DB, no service imports)
that is the code-level half of the audit lockstep. Registering a member here
without its twin in ``database/models/audit_log.py`` ``_UI_VISIBLE_V2_ACTIONS``
(and the platform log filter + ``bs.json`` in three languages) means the row
lands in the DB and never shows up on the "系统操作" page — design pit 21.

Why a **separate family from F054's ``app.publish``**: that action name is
already taken by the *state action* "the application went online". The publish
pipeline emits sixteen events around it (submitted / precheck failed / scan
blocked / version created / …), and nesting them under the same prefix makes
both the audit filter and ``_V2_NAMESPACE_TO_ACTION_PREFIX`` ambiguous
(design D12). The ``"app"`` namespace itself is shared and was created by
F054 — do not add a second one.

Audit rows of this family carry ``target_type='app_version'`` /
``target_id=version_id``, with ``app_id`` / ``version_no`` / ``deployment_id``
in metadata. The approval module's own audit rows are **not** a substitute:
their ``target_type`` is always ``approval_instance`` / ``approval_task``, so
"filter the audit page by application" cannot be answered from them (pit 20).
"""

from __future__ import annotations

from enum import StrEnum


class AppReleaseAuditAction(StrEnum):
    """``audit_log.action`` values owned by F055 (family ``app.release.``)."""

    #: A package was accepted by ``POST /api/v2/apps/deploy``.
    SUBMIT = "app.release.submit"
    PRECHECK_FAILED = "app.release.precheck_failed"
    SCAN_BLOCKED = "app.release.scan_blocked"
    VERSION_CREATED = "app.release.version_created"
    APPROVAL_CREATED = "app.release.approval_created"
    #: The gate resolved no approver and returned ``decision=EXCEPTION``.
    APPROVAL_EXCEPTION = "app.release.approval_exception"
    #: The submitter was also the resolved approver and the node auto-passed.
    SELF_APPROVAL = "app.release.self_approval"
    APPROVED = "app.release.approved"
    REJECTED = "app.release.rejected"
    WITHDRAWN = "app.release.withdrawn"
    #: The application was deleted, so the in-flight request was cancelled.
    CANCELLED = "app.release.cancelled"
    ONLINE = "app.release.online"
    #: Approved but parked — capacity admission or the start itself failed.
    PENDING_ONLINE = "app.release.pending_online"
    MANUAL_PUBLISH = "app.release.manual_publish"
    #: Capability declaration of a release (AC-55) — first writer lands with
    #: the capability bus wave; registered now so the whitelist is touched once.
    CAPABILITY_DECLARED = "app.release.capability_declared"
    #: The two-phase compensation after "approval created, version INSERT
    #: failed" (design D6).
    ROLLBACK = "app.release.rollback"


#: Audit ``target_type`` of every event in this family — see the module docstring.
RELEASE_AUDIT_TARGET_TYPE = "app_version"
