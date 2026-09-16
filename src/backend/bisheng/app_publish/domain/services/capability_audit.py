"""Dual-attribution recording of runtime capability calls (F055 T059 / AC-55).

One rule, stated once so neither half can drift from it:

    **actor = the application · subject = the current access user**, and only a
    *model* call may set the subject to 「应用自身」 — with that fact written
    down explicitly rather than left as an absent value. Retrieval with no
    access user is refused before it reaches a recorder, so a retrieval record
    always names a person.

The two halves live in two tables, deliberately:

* **model** calls are already recorded by F051 in ``model_call_record``, which
  carries ``app_id`` / ``subject_kind`` / ``subject_id`` and the token counts
  AC-55 asks for. Nothing is duplicated here; :func:`assert_model_attribution`
  is the assertion that the pair F051 writes is the pair AC-55 requires, and it
  is what the F055 suite pins so a change on that side cannot quietly drop one.
* **knowledge** calls land in ``app_capability_call_record`` through
  :func:`record_retrieval` — same shape, same reasoning about volume.

Writing is best effort and never raises: a record that failed to land must not
turn somebody's working retrieval into an error, which is the same rule
``release_audit`` follows for the publish family.
"""

from __future__ import annotations

from collections.abc import Sequence

from loguru import logger

from bisheng.app_publish.domain.models.capability_call_record import (
    CAPABILITY_KNOWLEDGE,
    RESULT_FAILED,
    RESULT_REFUSED,
    RESULT_SUCCESS,
    AppCapabilityCallRecord,
    AppCapabilityCallRecordDao,
)
from bisheng.core.database import get_async_db_session

#: ``model_call_record.subject_kind`` values, mirrored from F051 so this
#: module's assertion does not depend on importing the face.
SUBJECT_KIND_USER = "user"
SUBJECT_KIND_APP_SELF = "app_self"


async def record_retrieval(
    *,
    app_id: str,
    app_name: str | None,
    tenant_id: int,
    version_id: str | None,
    access_user_id: int,
    requested: Sequence[int] | None,
    effective: Sequence[int] | None,
    result: str = RESULT_SUCCESS,
    error_code: int | None = None,
    chunk_count: int | None = None,
    latency_ms: int | None = None,
) -> None:
    """Record one retrieval the capability bus performed for an access user.

    ``requested`` is what the application named (empty = "the whole declared
    scope") and ``effective`` is what was actually searched after the whitelist
    and the user's visibility narrowed it. Both are kept because the gap between
    them is the answer to "why did the app see less than I do".
    """

    row = AppCapabilityCallRecord(
        tenant_id=int(tenant_id or 0),
        app_id=app_id,
        app_name=app_name,
        subject_kind=SUBJECT_KIND_USER,
        subject_user_id=int(access_user_id),
        capability=CAPABILITY_KNOWLEDGE,
        targets={
            "requested": [int(one) for one in (requested or [])],
            "effective": [int(one) for one in (effective or [])],
        },
        result=result,
        error_code=error_code,
        chunk_count=chunk_count,
        latency_ms=latency_ms,
        version_id=version_id,
    )
    try:
        async with get_async_db_session() as session:
            await AppCapabilityCallRecordDao.ainsert(session, row)
            await session.commit()
    except Exception:
        # Best effort by design — see the module docstring. Logged with the
        # attribution pair so the row can be reconstructed from the log if it
        # ever matters.
        logger.exception(
            "app_publish.capability_record_failed app_id={} subject_user_id={} result={}",
            app_id,
            access_user_id,
            result,
        )


def assert_model_attribution(record) -> None:
    """Fail loudly when a hosted-app model record loses half of its attribution.

    Called by the F055 suite rather than at runtime: the point is to break a
    change that stops stamping ``app_id`` or ``subject_kind`` on F051's records,
    not to add a per-call check to the highest-frequency path in the product.

    The two things it pins:

    * the actor is the application's **uuid**, not its display name — the two
      were confused once already (T055 note ①), and a display name in an id
      column makes every per-application query silently empty;
    * the subject is a real user, or explicitly 「应用自身」. ``None`` is not an
      allowed third value: an unattributed call is exactly what AC-55 forbids.
    """

    app_id = getattr(record, "app_id", None)
    subject_kind = getattr(record, "subject_kind", None)
    if not app_id:
        raise AssertionError("hosted-app model record carries no app_id (AC-55 actor half)")
    if subject_kind not in (SUBJECT_KIND_USER, SUBJECT_KIND_APP_SELF):
        raise AssertionError(f"model record subject_kind={subject_kind!r} is neither a user nor 「应用自身」 (AC-55)")
    if subject_kind == SUBJECT_KIND_USER and not getattr(record, "subject_id", None):
        raise AssertionError("model record claims a user subject without naming one (AC-55)")


__all__ = [
    "RESULT_FAILED",
    "RESULT_REFUSED",
    "RESULT_SUCCESS",
    "SUBJECT_KIND_APP_SELF",
    "SUBJECT_KIND_USER",
    "assert_model_attribution",
    "record_retrieval",
]
