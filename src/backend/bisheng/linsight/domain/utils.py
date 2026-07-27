import asyncio
import json
import os
import uuid
from typing import Any

from loguru import logger

from bisheng.api.services.invite_code.invite_code import InviteCodeService
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.linsight.domain.models.linsight_execute_task import (
    ExecuteTaskStatusEnum,
    LinsightExecuteTask,
    LinsightExecuteTaskDao,
)
from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersion,
    LinsightSessionVersionDao,
    SessionVersionStatusEnum,
)
from bisheng.utils import util


# Get all manipulated files in a task
async def get_all_files_from_session(
    execution_tasks: list[LinsightExecuteTask], file_details: list[dict]
) -> list[Any] | list[Exception | BaseException | None]:
    """
    Get all manipulated files in a session
    :param file_details:
    :param execution_tasks: Execute Task List
    :return: List with file details
    """
    # Process File List
    all_from_session_files = file_details

    # Deduplication
    seen = set()
    all_from_session_files = [
        file
        for file in all_from_session_files
        if (file_tuple := (file["file_name"], file["file_path"], file["file_md5"])) not in seen
        and not seen.add(file_tuple)
    ]

    if not all_from_session_files:
        logger.warning("No files found that were manipulated in the session")
        return []

    # Upload files toMinIO
    async def upload_file_to_minio(file_info: dict) -> dict | None:
        """Upload files toMinIOand returns file information"""
        try:
            minio_client = await get_minio_storage()
            # ASCII-only object key (file_id + ext). A non-ASCII key breaks presigned
            # URL signatures on some S3-compatible backends (e.g. Huawei OBS → 403
            # SignatureDoesNotMatch). The original name stays on file_info["file_name"]
            # for display/download — the object key never needs to be human-readable.
            ext = os.path.splitext(file_info["file_name"])[1]
            object_name = f"linsight/session_files/{execution_tasks[0].session_version_id}/{file_info['file_id']}{ext}"
            # Use async upload if available, otherwise wrap sync call
            await minio_client.put_object(
                bucket_name=minio_client.bucket, object_name=object_name, file=file_info["file_path"]
            )
            file_info["file_url"] = object_name
            return file_info
        except Exception as e:
            logger.error(f"Upload files toMinIOKalah {file_info['file_name']}: {e}")
            return None

    # Upload files in parallel toMinIO
    upload_tasks = [upload_file_to_minio(file_info) for file_info in all_from_session_files]
    upload_results = await asyncio.gather(*upload_tasks, return_exceptions=True)
    # Filter failed uploads
    all_from_session_files = [
        result for result in upload_results if result is not None and not isinstance(result, Exception)
    ]
    # Record failed uploads
    failed_uploads = [result for result in upload_results if isinstance(result, Exception)]

    if failed_uploads:
        logger.warning(f"Some files failed to upload: {len(failed_uploads)} files")

    logger.debug(
        f"Number of files manipulated in the session: {len(all_from_session_files)}Document Description: {all_from_session_files}"
    )

    return all_from_session_files


# Workspace zones of the task working dir (design §9.3.2). ``output/`` is the
# delivery zone; ``scratch/`` is intermediate state and ``uploads/`` holds the
# user's own source files — neither is ever a deliverable.
OUTPUT_ZONE = "output"
SCRATCH_ZONE = "scratch"
UPLOADS_ZONE = "uploads"


def snapshot_file_paths(file_dir: str) -> set[str]:
    """Absolute paths of every file currently in ``file_dir``.

    Taken once at task start (right after the uploaded sources are prefetched) so
    the deliverable scan can later tell "the agent produced this" from "this was
    already here". Without the baseline the working dir is undifferentiated: the
    prefetched upload sources sit at the root next to anything the agent writes.
    """
    if not file_dir or not os.path.exists(file_dir):
        return set()
    return set(util.read_files_in_directory(file_dir))


def _zone_of(rel_path: str) -> str:
    """First path segment of a workspace-relative path ('' for root-level files)."""
    head = rel_path.replace(os.sep, "/").split("/", 1)
    return head[0] if len(head) > 1 else ""


# How likely a file type is to BE the deliverable rather than a part of one.
# A task's output/ zone is almost always "one main artifact + its ingredients":
# charts and images belong to the report, not the other way round. Ranking by type
# therefore picks the headline artifact far more reliably than recency does — a run
# that writes 报告.docx and then renders three charts ends with a PNG as its newest
# file, which is exactly the wrong thing to put in "已为您整理好 X".
_DELIVERABLE_TYPE_RANK: dict[str, int] = {
    # documents — the headline artifact in almost every task
    ".md": 0,
    ".markdown": 0,
    ".docx": 0,
    ".doc": 0,
    ".pdf": 0,
    ".html": 0,
    ".htm": 0,
    ".rtf": 0,
    ".odt": 0,
    # spreadsheets
    ".xlsx": 1,
    ".xls": 1,
    ".csv": 1,
    ".ods": 1,
    # presentations
    ".pptx": 2,
    ".ppt": 2,
    ".odp": 2,
    # images / charts — nearly always an ingredient of a report, not the report
    ".png": 4,
    ".jpg": 4,
    ".jpeg": 4,
    ".gif": 4,
    ".svg": 4,
    ".webp": 4,
    ".bmp": 4,
}
# Unknown extensions (.zip, .ipynb, …) sit between presentations and images: they
# can legitimately be the deliverable, so they must not lose to a chart.
_DEFAULT_TYPE_RANK = 3


def _type_rank(file_info: dict) -> int:
    ext = os.path.splitext(file_info.get("file_name") or "")[1].lower()
    return _DELIVERABLE_TYPE_RANK.get(ext, _DEFAULT_TYPE_RANK)


# Read File Directory File Details
async def read_file_directory(file_dir: str) -> list[dict[str, Any]]:
    """Read file details in file directory"""
    if not file_dir or not os.path.exists(file_dir):
        return []

    files = util.read_files_in_directory(file_dir)
    file_details = []
    for file in files:
        file_md5 = await util.async_calculate_md5(file)
        try:
            file_mtime = os.path.getmtime(file)
        except OSError:
            # raced away between listing and stat; sorts last, still listed
            file_mtime = 0.0
        file_details.append(
            {
                "file_name": os.path.basename(file),
                "file_path": file,
                # workspace-relative path — carries the zone (output/ vs scratch/
                # vs root), which ``file_path`` alone cannot express portably
                "rel_path": os.path.relpath(file, file_dir),
                "file_mtime": file_mtime,
                "file_md5": file_md5,
                "file_id": uuid.uuid4().hex[:8],  # Generate unique filesID
            }
        )

    return file_details


def select_deliverables(file_details: list[dict], baseline_paths: set[str] | None = None) -> list[dict]:
    """Pick the run's deliverables out of the working-dir listing, best first.

    Two ordered criteria, no text matching:

    1. **The ``output/`` zone** — the delivery contract every writer is pointed at
       (the code interpreter now relocates root-level writes into it, and the
       kernel prompt tells ``write_file`` to use it).
    2. **Files this run created**, when ``output/`` came up empty — a deliverable
       written to an off-contract path is still a deliverable. Requires the task's
       start-of-run ``baseline_paths``; without it this criterion is skipped rather
       than guessed at.

    ``scratch/`` (intermediate) and ``uploads/`` (the user's own sources) are never
    deliverables under either criterion.

    Replaces the legacy "file name appears verbatim in the answer" heuristic, which
    was both too weak (the model routinely finishes without naming its file, so a
    real deliverable degraded into a synthesized ``报告.md``) and too strong (an
    uploaded source the model merely mentioned was promoted to deliverable — and,
    because ``os.walk`` yields the root before subdirectories, could outrank the
    real ``output/`` file and become the headline artifact).

    The two criteria are mutually exclusive. The result is ordered by file TYPE
    first and recency second (see ``_DELIVERABLE_TYPE_RANK``), so ``files[0]`` — the
    frontend's "已为您整理好 X" headline — is a deliberate pick rather than whatever
    ``os.walk`` happened to enumerate first (previously that was filesystem-
    dependent, and since ``os.walk`` is top-down it favoured root-level files over
    the real ``output/`` deliverable).
    """
    candidates = []
    for file_info in file_details:
        rel_path = file_info.get("rel_path") or os.path.basename(file_info.get("file_path") or "")
        zone = _zone_of(rel_path)
        if zone in (SCRATCH_ZONE, UPLOADS_ZONE):
            continue
        candidates.append((file_info, zone))

    selected = [info for info, zone in candidates if zone == OUTPUT_ZONE]
    if not selected and baseline_paths is not None:
        # `is not None`, not truthiness: an EMPTY baseline is the common case (a task
        # with no uploaded files prefetches nothing), and it is precisely the case
        # where every file present was produced by this run. Only `None` — no
        # baseline captured at all — means "cannot tell", and then we do not guess.
        selected = [info for info, _ in candidates if info.get("file_path") not in baseline_paths]

    # Type first, recency second. The frontend takes ``[0]`` as the headline file
    # and lists the rest under it, so this ordering is user-visible: it must be a
    # deliberate "which of these IS the deliverable" answer, not enumeration order.
    selected.sort(key=lambda info: (_type_rank(info), -(info.get("file_mtime") or 0.0)))
    return selected


# Get the final result file
async def get_final_result_file(
    session_model: LinsightSessionVersion, file_details, baseline_paths: set[str] | None = None
) -> list[dict]:
    """
    Get the final result file
    :param file_details:
    :param session_model: LinsightSessionVersion Model Instance
    :param baseline_paths: absolute paths present at task start (see snapshot_file_paths)
    :return: List containing final result file information
    """
    # Final Result File
    final_result_files = [
        {
            "file_name": file_info["file_name"],
            "file_path": file_info["file_path"],
            "file_md5": file_info["file_md5"],
            "file_id": file_info["file_id"],
        }
        for file_info in select_deliverables(file_details, baseline_paths)
    ]

    async def upload_file_to_minio(final_file_info: dict) -> dict | None:
        """Upload files toMinIOand returns file information"""
        try:
            # ASCII-only object key (file_id + ext) — non-ASCII keys break presigned
            # signatures on some S3-compatible backends (Huawei OBS → 403). Display
            # name stays on final_file_info["file_name"].
            ext = os.path.splitext(final_file_info["file_name"])[1]
            object_name = f"linsight/final_result/{session_model.id}/{final_file_info['file_id']}{ext}"
            # Use async upload if available, otherwise wrap sync call
            minio_client = await get_minio_storage()
            await minio_client.put_object(
                bucket_name=minio_client.bucket, object_name=object_name, file=final_file_info["file_path"]
            )
            final_file_info["file_url"] = object_name
            return final_file_info
        except Exception as e:
            logger.error(f"Upload files toMinIOKalah {final_file_info['file_name']}: {e}")
            return None

    # Upload files toMinIO (Parallel Processing)
    if final_result_files:
        upload_tasks = [upload_file_to_minio(final_file_info) for final_file_info in final_result_files]

        upload_results = await asyncio.gather(*upload_tasks, return_exceptions=True)

        # Filter failed uploads
        final_result_files = [
            result for result in upload_results if result is not None and not isinstance(result, Exception)
        ]

        # Record failed uploads
        failed_uploads = [result for result in upload_results if isinstance(result, Exception)]
        if failed_uploads:
            logger.warning(f"Some files failed to upload: {len(failed_uploads)} files")

    return final_result_files


# Filename of the synthesized fallback report (design §9.3.2 output/ zone).
FALLBACK_REPORT_NAME = "报告.md"


async def build_fallback_report_file(session_model: LinsightSessionVersion, answer: str, file_dir: str) -> list[dict]:
    """Backstop deliverable when the agent produced no ``output/`` file (F035).

    Weak models sometimes loop on planning (``write_todos``) and finish without
    ever calling ``write_file``, so :func:`get_final_result_file` finds nothing
    and the task ends with no report. To guarantee a deliverable, materialise the
    final answer as a markdown report under ``output/`` and upload it as a final
    result file (same MinIO scheme as real deliverables).

    Best-effort: returns ``[]`` on empty answer or any failure so the empty-handed
    completion still proceeds.
    """
    answer = (answer or "").strip()
    if not answer:
        return []
    try:
        output_dir = os.path.join(file_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        local_path = os.path.join(output_dir, FALLBACK_REPORT_NAME)
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(answer)
        file_md5 = await util.async_calculate_md5(local_path)

        # ASCII-only object key (file_id + ext): FALLBACK_REPORT_NAME is Chinese
        # ("报告.md"), and a non-ASCII key breaks presigned signatures on some
        # S3-compatible backends (Huawei OBS → 403). The Chinese name is kept as the
        # display/download file_name.
        file_id = uuid.uuid4().hex[:8]
        ext = os.path.splitext(FALLBACK_REPORT_NAME)[1]
        object_name = f"linsight/final_result/{session_model.id}/{file_id}{ext}"
        minio_client = await get_minio_storage()
        await minio_client.put_object(bucket_name=minio_client.bucket, object_name=object_name, file=local_path)
        logger.info("Fallback report synthesized from answer (no output/ deliverable was produced)")
        return [
            {
                "file_name": FALLBACK_REPORT_NAME,
                "file_path": local_path,
                "file_md5": file_md5,
                "file_id": file_id,
                "file_url": object_name,
            }
        ]
    except Exception as e:
        logger.warning(f"fallback report generation failed: {e}")
        return []


# Initiateworkerwhen checking for incomplete tasks and terminating
async def check_and_terminate_incomplete_tasks(node_id: str) -> None:
    """
    Check for incomplete tasks and terminate
    """

    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.linsight.worker import NodeManager

    redis_client = await get_redis_client()  # Get Redis Client
    node_manager = NodeManager(redis_client, node_id)  # Get Node Manager Instance

    # Worker-startup cleanup runs in the standalone Linsight worker without an
    # HTTP request, so no tenant ContextVar is set. Under multi_tenant.enabled the
    # first DAO query would otherwise raise NoTenantContextError (20004). This is a
    # deliberate cross-tenant sweep — it terminates every tenant's orphaned
    # IN_PROGRESS tasks — so bypass the tenant filter for the whole DB body.
    with bypass_tenant_filter():
        try:
            # Get all incomplete tasks from the database
            incomplete_tasks = await LinsightSessionVersionDao.get_session_versions_by_status(
                status=SessionVersionStatusEnum.IN_PROGRESS
            )

            if not incomplete_tasks:
                return

            tasks_to_terminate = []
            user_ids_to_rollback = set()

            for session in incomplete_tasks:
                session_id = session.id

                # Check task ownership in Redis
                owner_key = f"linsight:task:owner:{session_id}"
                owner_node_id = await redis_client.aget(owner_key)

                should_terminate = False

                if not owner_node_id:
                    # No owned node, task needs to be cleaned up.
                    should_terminate = True
                    logger.warning(f"Task {session_id} has no owner in Redis. Marking as failed.")
                else:
                    # There is an owned node, check if the node is alive
                    is_alive = await node_manager.is_node_alive(owner_node_id)
                    if not is_alive:
                        # Node is dead, task needs to be cleaned up.
                        should_terminate = True
                        logger.warning(f"Task {session_id} owner {owner_node_id} is dead. Marking as failed.")
                    else:
                        # Node is alive, skip cleanup
                        logger.info(f"Task {session_id} is running on active node {owner_node_id}. Skipping.")

                if should_terminate:
                    tasks_to_terminate.append(session_id)
                    user_ids_to_rollback.add(session.user_id)

            # 3. Batch-terminate only the sessions selected above.
            if tasks_to_terminate:
                await LinsightSessionVersionDao.batch_update_session_versions_status(
                    session_version_ids=tasks_to_terminate,
                    status=SessionVersionStatusEnum.FAILED,
                    output_result={"error_message": "Worker node crash detected"},
                )

                # Update the execution-task status for the terminated sessions.
                await LinsightExecuteTaskDao.batch_update_status_by_session_version_id(
                    session_version_ids=tasks_to_terminate,
                    status=ExecuteTaskStatusEnum.FAILED,
                    where=(
                        LinsightExecuteTask.status != ExecuteTaskStatusEnum.SUCCESS,
                        LinsightExecuteTask.status != ExecuteTaskStatusEnum.FAILED,
                    ),
                )

            logger.warning(f"Terminated {len(tasks_to_terminate)} incomplete tasks due to worker node crash.")

            system_config = await settings.aget_all_config()
            # DapatkanLinsight_invitation_code
            linsight_invitation_code = system_config.get("linsight_invitation_code", False)

            # Rollback invite code
            if linsight_invitation_code:
                for user_id in user_ids_to_rollback:
                    try:
                        await InviteCodeService.revoke_invite_code(user_id=user_id)
                        logger.info(f"User Rolled Back {user_id} Invitation code for")
                    except Exception as e:
                        logger.error(f"Rollback user {user_id} Invitation code failed for: {e}")

            else:
                logger.warning(
                    "Not enabled in system configuration Linsight Invitation code function, skip rollback operation"
                )

            logger.info("Check and terminate incomplete task action completed")
        except Exception as e:
            logger.error(f"Exception occurred while checking and terminating incomplete tasks: {e}")
            return


async def persist_task_turn_message(session_model: LinsightSessionVersion) -> ChatMessage:
    """F035 Track J (TJ-3): upsert the task turn into the unified conversation.

    A task turn is a plain bot ``ChatMessage`` in the same daily conversation
    (``chat_id == session_id``), marked ``category=\047task\047`` and carrying a
    pointer to the execution detail in ``extra.linsight_session_version_id`` so
    the frontend can lazy-load tasks/sop/files.

    Called twice in a turn's lifecycle: once at execution START (output_result
    empty -> a placeholder row with empty text, so a refresh mid-task/HITL still
    sees the in-flight turn in the stream and can re-hydrate its state by SV) and
    again at COMPLETION (success -> answer; failure -> error_message). Both find
    the existing row for this SV and UPDATE it in place; only the first call
    inserts. This keeps one bot row per task turn and avoids dangling questions.
    """
    output = session_model.output_result or {}
    answer = output.get("answer") or output.get("error_message") or ""
    svid = session_model.id

    # Find an existing bot task row for this SV (placeholder written at start).
    existing_rows = await ChatMessageDao.aget_messages_by_chat_id(
        chat_id=session_model.session_id, category_list=["task"], limit=1000
    )
    for row in existing_rows:
        if not row.is_bot:
            continue
        try:
            row_svid = json.loads(row.extra or "{}").get("linsight_session_version_id")
        except (json.JSONDecodeError, TypeError):
            row_svid = None
        if row_svid == svid:
            row.message = answer
            return await ChatMessageDao.aupdate_message_model(row)

    return await ChatMessageDao.ainsert_one(
        ChatMessage(
            user_id=session_model.user_id,
            chat_id=session_model.session_id,
            flow_id="",
            type="over",
            is_bot=True,
            sender="AI",
            category="task",
            message=answer,
            extra=json.dumps({"linsight_session_version_id": svid}),
            source=0,
        )
    )


async def get_task_feedback_by_version(session_id: str) -> dict[str, dict]:
    """Map each linsight session_version id -> its task ChatMessage feedback.

    The task result is a bot ``ChatMessage`` (``category="task"``) in the
    conversation ``session_id`` carrying ``extra.linsight_session_version_id``.
    The like/dislike verdict is stored on that ChatMessage row (unified with
    daily / knowledge / channel), so the standalone linsight page rates and
    echoes the highlight via the shared chatmessage feedback instead of a
    linsight-specific column.

    Returns ``{session_version_id: {"message_id": int, "liked": int}}``.
    """
    rows = await ChatMessageDao.aget_messages_by_chat_id(chat_id=session_id, category_list=["task"], limit=1000)
    result: dict[str, dict] = {}
    for row in rows:
        if not row.is_bot:
            continue
        try:
            svid = json.loads(row.extra or "{}").get("linsight_session_version_id")
        except (json.JSONDecodeError, TypeError):
            svid = None
        if svid:
            result[svid] = {"message_id": row.id, "liked": row.liked or 0}
    return result


async def persist_task_user_turn(chat_id: str, user_id: int, question: str, files: list | None = None) -> ChatMessage:
    """F035 Track J (TJ-3): persist the task user turn into the unified conversation.

    Mirrors the daily-chat question envelope (workstation/chat_service) so the
    user turn renders identically whether or not task mode was on for the round.
    """
    return await ChatMessageDao.ainsert_one(
        ChatMessage(
            user_id=user_id,
            chat_id=chat_id,
            flow_id="",
            type="over",
            is_bot=False,
            sender="User",
            category="question",
            message=json.dumps({"query": question or "", "files": files or []}, ensure_ascii=False),
            files=json.dumps(files) if files else None,
            extra="{}",
            source=0,
        )
    )


def _extract_user_query(message: str | None) -> str:
    """Unwrap the daily question envelope ``{"query","files"}``; fall back to raw text."""
    if not message:
        return ""
    try:
        data = json.loads(message)
        if isinstance(data, dict) and "query" in data:
            return str(data.get("query") or "")
    except (json.JSONDecodeError, TypeError):
        pass
    return message


async def build_prior_conversation_summary(chat_id: str, max_chars: int = 8000) -> str:
    """F035 Track J (TJ-5): rebuild prior conversation context from ChatMessage.

    Reads the unified conversation stream (by ``chat_id``) and pairs each user
    question with its following NON-EMPTY bot answer — both daily and task turns.
    The CURRENT task turn is excluded: at submit time its bot ChatMessage is
    created as an EMPTY placeholder (filled with the result only after the task
    finishes), and a turn whose bot answer is empty is skipped — so at task start
    the current question never pairs with an empty "助手:" and is never duplicated
    (it is also seeded directly into the agent input by ``_build_agent_input``).

    ``max_chars`` caps the injected context (design §3.8 — long histories must not
    blow the window). Retention is deterministic head+tail: the FIRST turn (the
    user's original requirements) is ALWAYS kept, the remaining budget holds the
    most-recent turns, and any elided middle turns are flagged. This is truncation,
    not a semantic summary — a true LLM summary is a separate follow-up.
    Returns "" if there is no prior completed Q/A.
    """
    messages = await ChatMessageDao.aget_messages_by_chat_id(chat_id=chat_id, limit=1000)
    pairs: list[str] = []  # chronological "用户/助手" blocks, one per completed turn
    pending_question: str | None = None
    for msg in messages or []:
        if not msg.is_bot:
            pending_question = _extract_user_query(msg.message)
        elif pending_question is not None:
            # The bot message consumes the pending question regardless; only RECORD
            # the pair when the bot actually answered. An empty bot message is the
            # current task turn's placeholder (created at submit, filled with the
            # result only after the task finishes) — pairing it would duplicate the
            # current question with an empty "助手:". An empty answer is not a
            # "completed prior Q/A".
            answer = msg.message or ""
            if answer.strip():
                pairs.append(f"用户: {pending_question}\n助手: {answer}")
            pending_question = None

    if not pairs:
        return ""

    # Deterministic head+tail retention (NOT an LLM summary): always keep the
    # FIRST turn — it usually carries the user's original requirements, which a
    # naive "keep most recent" truncation silently drops on long histories,
    # letting the deliverable drift from the founding ask. Fill the rest of the
    # budget with the most-recent turns (newest first); flag any elided middle.
    first = pairs[0]
    rest = pairs[1:]
    kept_tail: list[str] = []
    used = len(first)
    for block in reversed(rest):
        # Always keep at least the most-recent turn; then respect the budget.
        if kept_tail and used + len(block) > max_chars:
            break
        kept_tail.append(block)
        used += len(block)
    kept_tail.reverse()

    dropped = len(rest) - len(kept_tail)
    blocks = [first]
    if dropped > 0:
        blocks.append(f"(...此处省略中间 {dropped} 轮较早对话...)")
    blocks.extend(kept_tail)
    return "# 前情回顾(本会话此前的对话)\n" + "\n".join(blocks)
