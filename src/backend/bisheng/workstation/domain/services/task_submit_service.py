"""Shared task-mode submit core (F073).

Both the workbench SSE entry (``chat_service._task_mode_stream_completion``) and
the Open API JSON entry create a task turn the same way: session + version →
task-turn row → enqueue. Keeping one implementation stops the two from drifting
(the "persist before enqueue" race fix below was learned the hard way).

Content safety and title generation are deliberately NOT in here: the two
callers answer a blocked input differently (the workbench records the blocked
turn, the Open API writes nothing) and generate titles differently.
"""

from __future__ import annotations

from loguru import logger

from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.open_api import OpenApiTaskQueueUnavailableError
from bisheng.database.models.session import MessageSession
from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersion,
    LinsightSessionVersionDao,
    SessionVersionStatusEnum,
)
from bisheng.workstation.domain.schemas.chat import APIChatCompletion

ENQUEUE_FAILED_MESSAGE = "The task could not be queued for execution"


async def submit_task_turn(
    data: APIChatCompletion,
    login_user: UserPayload,
    *,
    session_subject: SessionSubject | None = None,
    api_meta: dict | None = None,
    telemetry_source: str = "platform",
    session_name: str = "New Chat",
    strict_enqueue: bool = False,
) -> tuple[MessageSession, LinsightSessionVersion]:
    """Create the task turn and hand it to the linsight queue.

    ``strict_enqueue=False`` (workbench): an enqueue failure is logged and the
    browser's later start-execute is the fallback. ``strict_enqueue=True``
    (Open API, no browser to fall back on): an enqueue failure marks the version
    failed and raises 26068 (HTTP 503), so the caller never receives an id for a
    task that will not run.
    """
    # Local imports avoid a module-level workstation->linsight cycle.
    from bisheng.linsight.domain import utils as linsight_execute_utils
    from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl
    from bisheng.workstation.domain.services.chat_service import _to_linsight_submit

    submit_obj = _to_linsight_submit(data)
    # Pass the original daily-shape files (filepath/type/file_id) so the user
    # question turn persists its attachments and they render after a refresh
    # (the submit schema's SubmitFileSchema drops the display fields).
    session, session_version = await LinsightWorkbenchImpl.submit_user_question(
        submit_obj,
        login_user,
        display_files=data.files,
        session_subject=session_subject,
        api_meta=api_meta,
        telemetry_source=telemetry_source,
        session_name=session_name,
    )

    # Persist the bot task turn BEFORE enqueueing. The worker's start-time call
    # (`_execute_workflow`) is the same find-then-insert upsert with no unique
    # key, and an idle worker dequeues within milliseconds — persisting after
    # the enqueue raced it, both sides found no row, and every task turn landed
    # as two category="task" rows (the whole task panel rendered twice in the
    # conversation). Writing the row first makes the worker's call a plain
    # update. Best-effort on its own: a persist failure must not stop the run.
    try:
        await linsight_execute_utils.persist_task_turn_message(session_version)
    except Exception:
        logger.exception(
            f"[TASK_SUBMIT] task turn persist failed chat_id={session_version.session_id} "
            f"svid={session_version.id}; the worker writes the row at execution start"
        )

    # Enqueue HERE, not from the browser: the run must not depend on the client
    # coming back (refresh, closed tab, proxy timeout). The workbench client's
    # start-execute remains a late retry and is safe to arrive after this — the
    # executor rejects re-entry on an already-running session.
    try:
        await linsight_execute_utils.enqueue_session_for_execution(session_version)
    except Exception as exc:
        if not strict_enqueue:
            logger.exception(
                f"[TASK_SUBMIT] server-side enqueue failed chat_id={session_version.session_id} "
                f"svid={session_version.id}; relying on client start-execute"
            )
            return session, session_version
        logger.exception(
            f"[TASK_SUBMIT] server-side enqueue failed chat_id={session_version.session_id} "
            f"svid={session_version.id}; marking the version failed"
        )
        await _mark_enqueue_failed(session_version, linsight_execute_utils)
        raise OpenApiTaskQueueUnavailableError() from exc

    return session, session_version


async def _mark_enqueue_failed(session_version: LinsightSessionVersion, linsight_execute_utils) -> None:
    session_version.status = SessionVersionStatusEnum.FAILED
    session_version.output_result = {
        "error_message": ENQUEUE_FAILED_MESSAGE,
        "error_type": "service_unavailable",
    }
    try:
        await LinsightSessionVersionDao.insert_one(session_version)
        await linsight_execute_utils.persist_task_turn_message(session_version)
    except Exception:
        logger.exception(f"[TASK_SUBMIT] could not record the enqueue failure svid={session_version.id}")


__all__ = ["ENQUEUE_FAILED_MESSAGE", "submit_task_turn"]
