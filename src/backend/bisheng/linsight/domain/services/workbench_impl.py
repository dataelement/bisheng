import asyncio
import json
import mimetypes
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from io import BytesIO
from typing import Any
from urllib.parse import unquote

from e2b.sandbox.filesystem.filesystem import WriteEntry
from fastapi import UploadFile
from langchain_core.tools import BaseTool
from loguru import logger

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum, BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeFileNotSupportedError
from bisheng.common.errcode.linsight import (
    LinsightFileTooLargeError,
    LinsightFolderDepthExceededError,
    LinsightFolderFileCountExceededError,
    LinsightFolderTotalSizeExceededError,
)
from bisheng.common.schemas.telemetry.event_data_schema import NewMessageSessionEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.common.utils.think_tags import strip_think_block
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.cache.utils import save_file_to_folder
from bisheng.core.logger import trace_id_var
from bisheng.core.prompts.manager import get_prompt_manager
from bisheng.core.storage.chat_attachment import promote_chat_attachments
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.database.models.flow import FlowType
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.knowledge.domain.models.knowledge import KnowledgeRead, KnowledgeTypeEnum
from bisheng.linsight.domain import utils as linsight_execute_utils
from bisheng.linsight.domain.models.linsight_execute_task import LinsightExecuteTaskDao
from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersion,
    LinsightSessionVersionDao,
)
from bisheng.linsight.domain.schemas.linsight_schema import (
    DownloadFilesSchema,
    LinsightQuestionSubmitSchema,
    SubmitFileSchema,
)
from bisheng.llm.domain.llm import BishengLLM
from bisheng.llm.domain.services import LLMService
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.tool.domain.services.executor import ToolExecutor
from bisheng.utils import util
from bisheng.utils.util import async_calculate_md5
from bisheng_langchain.gpts.tools.code_interpreter.e2b_executor import SIZE_AUTOPUSH


@dataclass
class TaskNode:
    """Task node to build the task tree"""

    task: Any  # LinsightExecuteTask Objects
    children: list["TaskNode"] = None

    def __post_init__(self):
        if self.children is None:
            self.children = []

    def to_dict(self) -> dict:
        """Convert task nodes to dictionary format"""
        task_dict = self.task.model_dump()
        task_dict["children"] = [child.to_dict() for child in self.children]
        return task_dict


class LinsightWorkbenchImpl:
    """LinsightWorkbench Implementation Class"""

    # Class Constant
    LINSIGHT_MEDIA_INGEST_LOG_PREFIX = "[linsight.media_ingest]"
    FILE_INFO_REDIS_KEY_PREFIX = "linsight_file:"
    CACHE_EXPIRATION_HOURS = 24
    # Image uploads preview as the picture itself (not their OCR/caption markdown),
    # so the original bytes are persisted into the workspace (see _parse_file /
    # _ingest_one_file / _ingest_daily_file → entry["original_file_path"]).
    _IMAGE_EXTS = frozenset({"png", "jpg", "jpeg", "gif", "webp", "bmp"})
    # Types whose ORIGINAL bytes stay useful after parsing, because the markdown
    # view is lossy in a way that defeats the user's actual intent: a spreadsheet
    # loses cell types / sheets / formulas (and ExcelLoader is a RAG chunker that
    # hard-fails past 10k chars), a Word file loses styling, a PDF loses table
    # geometry. These land in the workspace ALONGSIDE the .md so
    # ``bisheng_code_interpreter`` can open them with pandas / python-docx / fitz.
    # Images are deliberately absent: their originals are already promoted for
    # frontend preview, and feeding one back through ``read_file`` yields an
    # ``image`` block that a non-vision model rejects.
    _RAW_KEEP_EXTS = frozenset({"xlsx", "xls", "csv", "docx", "doc", "pptx", "ppt", "pdf", "ofd"})
    # Ceiling for carrying an original into the workspace + local task dir. Past
    # this, the .md view is the only thing worth the storage and the download
    # latency on every task start.
    _RAW_KEEP_MAX_BYTES = 50 * 1024 * 1024

    # ---- Folder upload (task mode) ------------------------------------------
    # A submission that carries any ``relative_path`` is a folder upload and is
    # gated by these three numbers. The frontend enforces the same values before
    # a single byte is uploaded (instant feedback, all-or-nothing); these are the
    # authoritative server-side check, so they are normally never hit.
    # Depth is counted in DIRECTORY segments, matching knowledge-space
    # ``MAX_FOLDER_DEPTH``; the file name itself does not count as a level.
    _FOLDER_MAX_FILES = 100
    _FOLDER_MAX_TOTAL_BYTES = 500 * 1024 * 1024
    _FOLDER_MAX_DEPTH = 10

    # ``mimetypes`` reads the SYSTEM mime database, which on a stock Linux image
    # (every deploy target, and CI) knows nothing about the OOXML types — xlsx /
    # docx / pptx all resolve to None there and every original lands in MinIO as
    # application/octet-stream, so the browser downloads instead of previewing.
    # macOS ships them, which is why this only shows up off the dev machine.
    # Pin the ones we actually carry so the stored content type is platform-stable.
    _RAW_CONTENT_TYPES = {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls": "application/vnd.ms-excel",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc": "application/msword",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "ppt": "application/vnd.ms-powerpoint",
        "pdf": "application/pdf",
        "csv": "text/csv",
        "ofd": "application/ofd",
    }

    @classmethod
    def _content_type_for(cls, filename: str) -> str:
        """Content type for a raw original, independent of the host mime database."""
        ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
        return cls._RAW_CONTENT_TYPES.get(ext) or mimetypes.guess_type(filename or "")[0] or "application/octet-stream"

    @classmethod
    def _is_media_filename(cls, filename: str | None) -> bool:
        from bisheng.knowledge.domain.upload_file_size import is_media_filename

        return is_media_filename(filename)

    @classmethod
    def _media_kind_label(cls, filename: str | None) -> str:
        from bisheng.knowledge.domain.upload_file_size import get_file_extension

        ext = get_file_extension(filename)
        return "video" if ext in {"mp4", "mov", "avi", "mkv", "webm"} else "audio"

    @classmethod
    def _log_media_ingest(cls, event: str, *, stage: str, chat_id: str, file_id: str, file_name: str, **fields) -> None:
        """Structured, grep-friendly media parse telemetry at task submit ingestion."""
        suffix = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
        logger.info(
            "{} {} stage={} chat_id={} file_id={} file={}{}",
            cls.LINSIGHT_MEDIA_INGEST_LOG_PREFIX,
            event,
            stage,
            chat_id,
            file_id,
            file_name,
            f" {suffix}" if suffix else "",
        )

    class LinsightError(Exception):
        """LinsightRelated Errors"""

        pass

    class SearchSOPError(Exception):
        """SOPRetrieve Error"""

        def __init__(self, error_class: BaseErrorCode):
            super().__init__(error_class.Msg)
            self.error_class = error_class

    class ToolsInitializationError(Exception):
        """Tool initialization error"""

    class BishengLLMError(Exception):
        """Bisheng LLMRelated Errors"""

    @classmethod
    async def _get_llm(cls, invoke_user_id: int) -> (BishengLLM, Any):
        # Get and validate the workbench configuration
        workbench_conf = await cls._get_workbench_config()

        # BuatLLMInstances
        linsight_conf = settings.get_linsight_conf()
        llm = await LLMService.get_bisheng_linsight_llm(
            invoke_user_id=invoke_user_id,
            model_id=workbench_conf.linsight_default_model_id,
            temperature=linsight_conf.default_temperature,
        )
        return llm, workbench_conf

    @classmethod
    async def human_participate_add_file(
        cls, linsight_session_version: LinsightSessionVersion, files: list[SubmitFileSchema]
    ) -> list | None:
        """
        Adding Files When Manually Involved
        :param linsight_session_version:
        :param files:
        :return:
        """
        if not files:
            return None

        # Workspace is keyed by session_version id (svid), matching WorkspaceBackend.
        processed_files = await cls._process_submitted_files(
            files, linsight_session_version.id, linsight_session_version.user_id
        )

        if linsight_session_version.files:
            linsight_session_version.files.extend(processed_files)
        else:
            linsight_session_version.files = processed_files

        await LinsightSessionVersionDao.insert_one(linsight_session_version)

        return processed_files

    @classmethod
    async def submit_user_question(
        cls,
        submit_obj: LinsightQuestionSubmitSchema,
        login_user: UserPayload,
        display_files: list[dict] | None = None,
        defer_ingest: bool = True,
    ) -> tuple[MessageSession, LinsightSessionVersion]:
        """
        Submit user issue and create session

        Args:
            submit_obj: Submitted Question Objects
            login_user: Logged in user information
            display_files: Original daily-shape attachment dicts (filepath/type/
                file_id) for the unified entry. Persisted on the user-question
                ChatMessage so the uploaded attachments render after a refresh,
                mirroring the daily-chat question envelope. ``None`` for the
                legacy /linsight entry (it renders attachments its own way).
            defer_ingest: Park the raw file refs in ``pending_files`` and let the
                worker ingest them (``ingest_pending_files``) instead of parsing
                them here. Ingestion runs the full ETL — 12 PDFs measured at 19
                minutes — so inline parsing put the whole batch inside one HTTP
                request, which nginx cut at 300s. Set False only where the caller
                genuinely needs the files materialized before it returns.

        Returns:
            tuple: (Message Session Model, Inspiration Conversation Version Model)

        Raises:
            LinsightError: When creating a session fails
        """
        try:
            # Metadata-only preconditions, always in-request: they carry the typed
            # codes the frontend branches on, which a deferred ingest could only
            # report minutes later as a generic task failure.
            cls.validate_submitted_files(submit_obj.files)
            # Continue an existing session when session_id is supplied, else
            # start a fresh one. Continuing reuses the MessageSession and only
            # appends a new version, so follow-up rounds stay in one 会话 (F035).
            continuing = bool(submit_obj.session_id)
            chat_id = submit_obj.session_id or uuid.uuid4().hex

            message_session = None
            if continuing:
                message_session = await MessageSessionDao.async_get_one(chat_id)
                if message_session is None or message_session.user_id != login_user.user_id:
                    # Stale / invalid / foreign session_id -> fall back to new.
                    continuing = False
                    chat_id = uuid.uuid4().hex

            # F035 fix: workspace attachments MUST be keyed by the session_version
            # id (svid), because the execution agent's WorkspaceBackend reads from
            # ``workspace/{svid}/``. In the unified model chat_id != svid, so
            # writing under chat_id left the uploaded file unreadable by the agent
            # (read_file -> MinIO NoSuchKey -> whole task failed). Generate the
            # svid up-front and use it both for ingestion and the version row id.
            svid = uuid.uuid4().hex
            # Process files (if present) — after chat_id is finalized
            if defer_ingest:
                processed_files = None
                pending_files = [f.model_dump() for f in (submit_obj.files or [])] or None
            else:
                processed_files = await cls._process_submitted_files(submit_obj.files, svid, login_user.user_id)
                pending_files = None

            if not continuing:
                # F035 Track J (unified conversation model): a task turn is not a
                # standalone session — when no session_id is supplied (first turn,
                # no daily conversation yet) the session is created as a daily
                # workstation conversation (flow_type=15), mirroring
                # workstation/chat_service. Task mode is a per-turn flag, never a
                # session type, so flow_type=LINSIGHT(20) is no longer minted here.
                message_session = MessageSession(
                    chat_id=chat_id,
                    name="New Chat",
                    flow_type=FlowType.WORKSTATION.value,
                    user_id=login_user.user_id,
                )

                message_session = await MessageSessionDao.async_insert_one(message_session)

                # RecordTelemetryJournal
                await telemetry_service.log_event(
                    user_id=login_user.user_id,
                    event_type=BaseTelemetryTypeEnum.NEW_MESSAGE_SESSION,
                    trace_id=trace_id_var.get(),
                    event_data=NewMessageSessionEventData(
                        session_id=message_session.chat_id,
                        app_id=ApplicationTypeEnum.DAILY_CHAT.value,
                        source="platform",
                        app_name=ApplicationTypeEnum.DAILY_CHAT.value,
                        app_type=ApplicationTypeEnum.DAILY_CHAT,
                    ),
                )

            # Create Ideas Conversation Version (id == svid used for the workspace)
            linsight_session_version = LinsightSessionVersion(
                id=svid,
                session_id=chat_id,
                user_id=login_user.user_id,
                question=submit_obj.question,
                tools=submit_obj.tools,
                org_knowledge_enabled=submit_obj.org_knowledge_enabled,
                personal_knowledge_enabled=submit_obj.personal_knowledge_enabled,
                organization_knowledge_ids=submit_obj.organization_knowledge_ids,
                knowledge_space_ids=submit_obj.knowledge_space_ids,
                files=processed_files,
                pending_files=pending_files,
                model=submit_obj.model,
                skills=submit_obj.skills,
            )
            linsight_session_version = await LinsightSessionVersionDao.insert_one(linsight_session_version)

            # F035 Track J: land the user question in the unified conversation
            # stream so the round reads as one Q→A pair regardless of task mode.
            # (The bot answer turn is written at completion in task_exec.)
            await linsight_execute_utils.persist_task_user_turn(
                chat_id=chat_id,
                user_id=login_user.user_id,
                question=submit_obj.question,
                # Deferring the ingest means EVERY attachment is still sitting in
                # the temp bucket here, so all of them get promoted — the chat
                # copy can no longer piggyback on the workspace original the
                # ingest used to have written by now. That is one extra
                # server-side copy_object per file, against a message whose
                # attachments would otherwise vanish with the temp bucket's 3-day
                # rule if the worker never ran. The parse result (video cover,
                # failed state) is stamped on later by the worker, via the
                # session_version_id pointer below.
                files=await promote_chat_attachments(
                    cls.annotate_display_files(display_files, processed_files), login_user.user_id
                ),
                session_version_id=svid,
            )

            return message_session, linsight_session_version

        except BaseErrorCode:
            # A typed business error (e.g. the folder-upload limits) already carries
            # the code the frontend branches on — re-wrapping it as a generic
            # LinsightError would launder that away into "submit failed".
            raise
        except Exception as e:
            logger.error(f"Failed to submit user question: {e!s}")
            raise cls.LinsightError(f"Failed to submit user question: {e!s}")

    @staticmethod
    def annotate_display_files(display_files: list[dict] | None, processed_files: list | None) -> list[dict] | None:
        """Stamp each persisted attachment with its parse result (by file_id).

        ``display_files`` are the daily-shape dicts the frontend renders; the
        ingestion result (``processed_files``) carries ``valid`` /
        ``parsing_status`` per file. Merging them lets the attachment chip show a
        "parse failed" state on reload instead of a normal-looking attachment the
        model can't actually use.

        Called twice per deferred turn: once here with ``processed_files=None``
        (a passthrough — submit no longer knows anything about the files) and
        again from the worker once the ingest produced them
        (``linsight_execute_utils.annotate_task_user_turn_files``).
        """
        if not display_files:
            return display_files
        status_by_id: dict[str, dict] = {}
        for p in processed_files or []:
            if isinstance(p, dict) and p.get("file_id") is not None:
                status_by_id[str(p["file_id"])] = p
        annotated: list[dict] = []
        for f in display_files:
            item = dict(f)
            fid = str(f.get("file_id") or f.get("id") or "")
            p = status_by_id.get(fid)
            if p is not None:
                item["valid"] = p.get("valid", True)
                item["parsing_status"] = p.get("parsing_status") or item.get("parsing_status")
                if p.get("error_message"):
                    item["error_message"] = p["error_message"]
                if p.get("cover_filepath"):
                    item["cover_filepath"] = p["cover_filepath"]
                # Ingestion already persisted the original image bytes for the
                # workspace preview; naming it here lets the conversation resolve
                # a fresh link for it too, the same way the other chat modes do.
                # Never overwrite a name that is already set: with the ingest
                # deferred, submit promotes the attachment out of the temp bucket
                # itself, and THAT key is the one conversation deletion sweeps.
                if p.get("original_file_path") and not item.get("object_name"):
                    item["object_name"] = p["original_file_path"]
            annotated.append(item)
        return annotated

    @classmethod
    async def _get_redis(cls):
        """Return the redis client (indirection so tests can patch it)."""
        return await get_redis_client()

    @classmethod
    def validate_submitted_files(cls, files: list[SubmitFileSchema] | None) -> None:
        """Cheap, pure-metadata preconditions — must stay in the request.

        These are the only source of the typed codes the frontend branches on
        (11021/11022/11023) and of the "file still parsing" rejection. They touch
        no MinIO, no Redis, no bytes; deferring them to the worker would turn a
        precise, immediate error into a generic task failure minutes later.
        """
        if not files:
            return
        for file in files:
            if file.parsing_status != "completed":
                raise cls.LinsightError(f"file {file.file_name} status is error: {file.parsing_status}")
        # Folder upload: reject an over-sized batch before any byte is copied.
        cls._validate_folder_upload(files)

    @classmethod
    async def ingest_pending_files(
        cls,
        session_model: LinsightSessionVersion,
        *,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
        should_abort: Callable[[], bool] | None = None,
    ) -> bool:
        """Materialize the attachments a deferred submit left on the row.

        Returns True when it ingested something. Rebinds ``files`` and clears
        ``pending_files`` on the passed model — the CALLER persists (the worker
        has to refresh the Redis snapshot in the same breath, so it owns the
        write).

        The rebind is deliberate: ``JsonType`` is a plain JSON column with no
        ``MutableList`` wrapper anywhere in this repo, so mutating the list in
        place emits no UPDATE at all and the ingest would silently vanish.
        """
        pending = session_model.pending_files
        if not pending:
            return False

        files = [SubmitFileSchema(**item) for item in pending]
        processed = await cls._process_submitted_files(
            files,
            session_model.id,
            session_model.user_id,
            on_progress=on_progress,
            should_abort=should_abort,
        )

        existing = session_model.files or []
        session_model.files = existing + (processed or [])
        session_model.pending_files = None
        return True

    @classmethod
    async def _process_submitted_files(
        cls,
        files: list[SubmitFileSchema] | None,
        chat_id: str,
        user_id: int = 0,
        *,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
        should_abort: Callable[[], bool] | None = None,
    ) -> list | None:
        """Process submitted files (F035: offload-first ingestion).

        For each submitted file:
          1. Resolve parsed-markdown metadata. Prefer the formal-bucket product
             already produced in this session (idempotent re-entry, TC-5); fall
             back to the temp metadata in Redis (``linsight_file:{file_id}``).
          2. Copy temp -> formal bucket only on first processing (skipped when a
             formal product already exists).
          3. Write the parsed markdown into the session **workspace**
             (``workspace/{chat_id}/uploads/<name>.md``) so deepagents file
             tools and E2B copy-in/out read it as the single truth (design §9.3.2).
          4. Attach pointer-block metadata (``workspace_path`` / ``line_count`` /
             ``image_count``) for ``prepare_file_list`` (zero body in prompt).

        If a file's temp metadata has expired (Redis miss) and no formal product
        exists, it is flagged invalid (``valid=False``, ``parsing_status="expired"``)
        rather than silently dropped, so the frontend can prompt a re-upload
        (design §9.3.8 key boundary).

        Args:
            files: List of submitted file references.
            chat_id: Session id; scopes the workspace prefix.
            on_progress: Awaited after each file with ``(done, total, file_name)``.
                Only the worker passes it, to keep the timeline alive while a
                deferred ingest runs; ``None`` keeps the original behaviour.
            should_abort: Polled BETWEEN files; truthy stops the loop and returns
                what was ingested so far. It bounds a stop to the file currently
                being parsed, not to the whole batch — an ETL already in flight
                (600s ceiling) still runs to completion, because nothing here can
                interrupt it.

        Returns:
            List of processed file metadata dicts (one per submitted file).
        """
        if not files:
            return None

        cls.validate_submitted_files(files)

        # Daily-bucket files (unified-resource) are parsed on-the-fly; only the
        # linsight-pipeline files need a Redis temp_info lookup.
        linsight_files = [f for f in files if not f.file_url]
        redis_keys = [f"{cls.FILE_INFO_REDIS_KEY_PREFIX}{f.file_id}" for f in linsight_files]
        redis_client = await cls._get_redis()
        temp_values = await redis_client.amget(redis_keys) if redis_keys else []
        # ``amget`` DROPS misses (``[loads(v) for v in values if v is not None]``),
        # so a single expired temp key makes the returned list shorter than the
        # keys — zipping it positionally would then staple B's markdown_file_path
        # onto A. Only pair by position when the lengths still prove alignment;
        # otherwise re-read key by key so each file gets its own value (or None).
        if len(temp_values) == len(linsight_files):
            temp_by_id = {f.file_id: t for f, t in zip(linsight_files, temp_values)}
        else:
            temp_by_id = {
                f.file_id: await redis_client.aget(f"{cls.FILE_INFO_REDIS_KEY_PREFIX}{f.file_id}")
                for f in linsight_files
            }

        minio_client = await get_minio_storage()

        processed_files: list[dict] = []
        # Track workspace filenames used in THIS submission so distinct files with
        # the same base name don't collide at the same uploads/<name> key.
        used_names: set[str] = set()
        media_files = [f for f in files if cls._is_media_filename(f.file_name)]
        if media_files:
            logger.info(
                "{} BATCH stage=submit_ingest chat_id={} media_count={} files={}",
                cls.LINSIGHT_MEDIA_INGEST_LOG_PREFIX,
                chat_id,
                len(media_files),
                ",".join(f.file_name for f in media_files),
            )
        total = len(files)
        for submit_file in files:
            if should_abort is not None and should_abort():
                logger.info(f"ingest aborted after {len(processed_files)}/{total} files chat_id={chat_id}")
                break
            try:
                if submit_file.file_url:
                    entry = await cls._ingest_daily_file(submit_file, chat_id, minio_client, user_id, used_names)
                else:
                    entry = await cls._ingest_one_file(
                        submit_file, temp_by_id.get(submit_file.file_id), chat_id, minio_client, used_names
                    )
            except Exception as e:
                # Degrade this file, never the batch. The daily branch already
                # degrades internally, but the linsight branch makes bare
                # copy_object calls, so one MinIO hiccup abandoned every
                # remaining attachment. Since the ingest moved into the worker
                # that loss is also silent — the run would simply proceed with
                # fewer files than the user attached.
                logger.exception(f"attachment ingest failed name={submit_file.file_name!r} chat_id={chat_id}: {e}")
                entry = {
                    "file_id": submit_file.file_id,
                    "original_filename": submit_file.file_name,
                    "relative_path": submit_file.relative_path,
                    "parsing_status": "failed",
                    "valid": False,
                    "error_message": str(e),
                }
            processed_files.append(entry)
            if on_progress is not None:
                await on_progress(len(processed_files), total, submit_file.file_name)

        return processed_files

    @classmethod
    async def _ingest_daily_file(
        cls,
        submit_file: SubmitFileSchema,
        chat_id: str,
        minio_client,
        user_id: int,
        used_names: set[str] | None = None,
    ) -> dict:
        """Ingest a DAILY-bucket file into the linsight workspace (unified-resource).

        The daily upload only stores the raw file (no parse). We reuse the same
        parser the daily chat uses (``TempFilePipeline``): download the raw file,
        extract its text/markdown, write that to the formal bucket, then drop it
        into the workspace as ``uploads/<original-name>.md`` so the offload-first
        file tools (read_file) + ``prepare_file_list`` pointer block see it like
        any linsight-uploaded attachment.

        Graceful degradation (never abort the task):
          - download fails -> nothing to fall back to: skip, mark ``valid=False``.
          - parse fails (raw downloaded) -> keep the ORIGINAL file in the
            workspace (``uploads/<original-name>.<ext>``) so the agent's ``ls``
            still shows it (user decision); mark ``valid=False`` for the chip.
        """
        from bisheng.api.v1.schemas import FileProcessBase
        from bisheng.core.cache.utils import async_file_download
        from bisheng.knowledge.rag.temp_file_pipeline import TempFilePipeline

        # 1) Download the raw daily-bucket file. A download failure can't be
        # recovered (no bytes for a fallback) — log the full traceback and skip.
        try:
            local_path, dl_name = await async_file_download(submit_file.file_url)
        except Exception as e:
            logger.exception(
                f"daily file download failed (name={submit_file.file_name!r} "
                f"url={submit_file.file_url!r} chat_id={chat_id})"
            )
            return {
                "file_id": submit_file.file_id,
                "original_filename": submit_file.file_name,
                "relative_path": submit_file.relative_path,
                "parsing_status": "failed",
                "valid": False,
                "error_message": f"file download failed: {e}",
            }

        file_name = submit_file.file_name or dl_name

        # 1.5) Route before parsing. Two of the three routes never had any business
        # calling the ETL: a passthrough type has no loader (or a lossy one) and a
        # ``.py`` would raise KnowledgeFileNotSupportedError purely so the except
        # branch below could catch it and do what we can do directly — at the cost
        # of a wasted round-trip and a logger.exception that reads like a real
        # failure. ``unsupported`` short-circuits for the same reason; the pipeline
        # would reject it on exactly the same extension check.
        route = cls._ingest_route(file_name)
        if route == "passthrough":
            raw = await cls._read_local_bytes(local_path)
            if raw is None:
                return {
                    "file_id": submit_file.file_id,
                    "original_filename": file_name,
                    "relative_path": submit_file.relative_path,
                    "parsing_status": "failed",
                    "valid": False,
                    "error_message": "file bytes unavailable after download",
                }
            return await cls._finalize_passthrough(submit_file, file_name, chat_id, minio_client, raw, used_names)
        if route == "unsupported":
            return await cls._keep_original_in_workspace(
                submit_file,
                file_name,
                chat_id,
                minio_client,
                local_path,
                KnowledgeFileNotSupportedError(),
                used_names,
            )

        is_media = cls._is_media_filename(file_name)
        parse_started = time.monotonic()
        if is_media:
            file_bytes: int | None
            try:
                file_bytes = os.path.getsize(local_path)
            except OSError:
                file_bytes = None
            cls._log_media_ingest(
                "START",
                stage="submit_ingest",
                chat_id=chat_id,
                file_id=submit_file.file_id,
                file_name=file_name,
                media_kind=cls._media_kind_label(file_name),
                file_bytes=file_bytes,
                user_id=user_id,
            )

        # 2) Parse to markdown. On failure we still have the raw bytes, so keep the
        # original file in the workspace instead of dropping it.
        try:
            file_rule = FileProcessBase(
                knowledge_id=0,
                separator=["\n\n", "\n"],
                separator_rule=["after", "after"],
                chunk_size=1000,
                chunk_overlap=0,
            )
            pipeline = TempFilePipeline(
                invoke_user_id=user_id,
                local_file_path=local_path,
                file_name=file_name,
                file_rule=file_rule,
            )
            result = await pipeline.arun()
            markdown = "\n\n".join(doc.page_content for doc in (result.documents or []) if doc.page_content)
            if is_media:
                loader_name = type(pipeline.loader).__name__ if pipeline.loader else "unknown"
                user_metadata: dict = {}
                if result.documents:
                    user_metadata = (result.documents[0].metadata or {}).get("user_metadata") or {}
                elapsed_ms = (time.monotonic() - parse_started) * 1000.0
                cls._log_media_ingest(
                    "OK",
                    stage="submit_ingest",
                    chat_id=chat_id,
                    file_id=submit_file.file_id,
                    file_name=file_name,
                    media_kind=cls._media_kind_label(file_name),
                    loader=loader_name,
                    elapsed_ms=f"{elapsed_ms:.1f}",
                    markdown_chars=len(markdown),
                    markdown_lines=(markdown.count("\n") + 1 if markdown else 0),
                    transcription_model_id=user_metadata.get("transcription_model_id"),
                    transcription_model_name=user_metadata.get("transcription_model_name"),
                )
        except Exception as e:
            if is_media:
                elapsed_ms = (time.monotonic() - parse_started) * 1000.0
                cls._log_media_ingest(
                    "FAIL",
                    stage="submit_ingest",
                    chat_id=chat_id,
                    file_id=submit_file.file_id,
                    file_name=file_name,
                    media_kind=cls._media_kind_label(file_name),
                    elapsed_ms=f"{elapsed_ms:.1f}",
                    error_type=type(e).__name__,
                    error=str(e)[:500],
                )
            logger.exception(
                f"daily file parse failed; keeping original in workspace (name={file_name!r} chat_id={chat_id})"
            )
            entry = await cls._keep_original_in_workspace(
                submit_file, file_name, chat_id, minio_client, local_path, e, used_names
            )
            if is_media:
                cls._log_media_ingest(
                    "DEGRADED",
                    stage="submit_ingest",
                    chat_id=chat_id,
                    file_id=submit_file.file_id,
                    file_name=file_name,
                    media_kind=cls._media_kind_label(file_name),
                    parsing_status=entry.get("parsing_status"),
                    valid=entry.get("valid"),
                    workspace_path=entry.get("workspace_path"),
                )
            return entry

        formal_object = cls._formal_markdown_object(submit_file.file_id, chat_id)
        await minio_client.put_object(
            bucket_name=minio_client.bucket, object_name=formal_object, file=markdown.encode("utf-8")
        )

        entry: dict = {
            "file_id": submit_file.file_id,
            "original_filename": file_name,
            "relative_path": submit_file.relative_path,
            "parsing_status": "completed",
            "valid": True,
            "markdown_file_path": formal_object,
        }
        # Persist the original bytes into the formal workspace bucket and record
        # their key — for images so the chip previews the picture, for
        # _RAW_KEEP_EXTS so the workspace carries the original next to the .md.
        ext = os.path.splitext(file_name)[1].lower().lstrip(".")
        if ext in cls._IMAGE_EXTS or cls._should_keep_raw(file_name, local_path):
            raw_bytes = await cls._read_local_bytes(local_path)
            if raw_bytes:
                formal_original = f"linsight/{chat_id}/{submit_file.file_id}_original.{ext}"
                await minio_client.put_object(
                    bucket_name=minio_client.bucket, object_name=formal_original, file=raw_bytes
                )
                entry["original_file_path"] = formal_original
        if cls._media_kind_label(file_name) == "video":
            try:
                from bisheng.workstation.domain.services.media_cover_service import WorkstationMediaCoverService

                cover_filepath = await WorkstationMediaCoverService.upload_video_cover(local_path, minio_client)
                if cover_filepath:
                    entry["cover_filepath"] = cover_filepath
            except Exception as cover_exc:
                logger.warning(
                    "video cover extraction during submit ingest failed: file={} error={}",
                    file_name,
                    cover_exc,
                )
        await cls._write_attachment_to_workspace(entry, chat_id, minio_client, used_names=used_names)
        return entry

    @classmethod
    async def _keep_original_in_workspace(
        cls,
        submit_file: SubmitFileSchema,
        file_name: str,
        chat_id: str,
        minio_client,
        local_path: str,
        error: Exception,
        used_names: set[str] | None,
    ) -> dict:
        """Parse-failure fallback: copy the raw original into the workspace.

        Three outcomes, by what the workspace can actually do with the original:

        1. **Text** (``_TEXT_LIKE_EXTS``) -> degrade to a passthrough SUCCESS. The
           file reads perfectly well as itself, so the parse failure cost nothing
           and reporting it as failed makes the chip cry wolf. This is what saves
           a large csv, whose ``ExcelLoader`` hard-fails past 10k chars while the
           csv sitting in the workspace is exactly what the user wanted analysed.
        2. **Binary with a consumer** (``_RAW_KEEP_EXTS`` / ``_IMAGE_EXTS``) ->
           ``failed`` + ``valid=False``. A broken pdf really is broken: there is no
           text view, and only the code interpreter can do anything with it.
        3. **Everything else** -> ``unsupported``, and it does not enter the
           workspace at all. An mp3 that no parser, no ``read_file`` and no code
           interpreter can open is pure cost: storage, a confusing ``ls`` entry,
           and a wasted tool call.

        The original always reaches the formal bucket first, so in all three cases
        the user can still download what they uploaded.
        """

        def _read_bytes(path: str) -> bytes:
            with open(path, "rb") as fh:
                return fh.read()

        raw = await asyncio.to_thread(_read_bytes, local_path)

        # Case 1. Same shape as a never-parsed passthrough file, so it goes through
        # the same builder rather than a parallel one that would drift from it.
        if cls._original_is_text(file_name):
            logger.info(
                "parse failed for {} but it is readable as text; using the original directly ({})",
                file_name,
                error,
            )
            return await cls._finalize_passthrough(
                submit_file, file_name, chat_id, minio_client, raw, used_names, degraded_from=error
            )

        ext = os.path.splitext(file_name)[1]
        formal_object = f"linsight/{chat_id}/{submit_file.file_id}{ext}"
        await minio_client.put_object(bucket_name=minio_client.bucket, object_name=formal_object, file=raw)

        usable = cls._original_is_usable(file_name)
        entry: dict = {
            "file_id": submit_file.file_id,
            "original_filename": file_name,
            "relative_path": submit_file.relative_path,
            "parsing_status": "failed" if usable else "unsupported",
            "valid": False,
            "error_message": (
                f"file parse failed, original kept: {error}"
                if usable
                else f"unsupported file type, original not usable in the workspace: {error}"
            ),
            "markdown_file_path": formal_object,
        }
        if usable:
            await cls._write_attachment_to_workspace(
                entry, chat_id, minio_client, as_markdown=False, used_names=used_names
            )
        return entry

    @classmethod
    async def _finalize_passthrough(
        cls,
        submit_file: SubmitFileSchema,
        file_name: str,
        chat_id: str,
        minio_client,
        raw: bytes,
        used_names: set[str] | None,
        *,
        degraded_from: Exception | None = None,
    ) -> dict:
        """Land a file in the workspace AS ITSELF, with no markdown view.

        Used for two situations that look different but produce the same result:
        a type we never intended to parse (``_ingest_route`` -> ``passthrough``),
        and a text file whose parse blew up but which is perfectly readable as-is
        (``degraded_from``). Either way the outcome is a file the agent can
        ``read_file`` and the code interpreter can open, so it is reported as a
        SUCCESS — the historical ``failed`` / ``valid=False`` marking made the
        chip cry wolf about a file that works.

        ``parsing_status`` stays ``"completed"`` on purpose. It is not "which
        pipeline ran", it is "is ingestion finished / may this be submitted": the
        frontend treats any other value as still-parsing (disabling send, polling
        forever) and ``_process_submitted_files`` rejects the submission outright.
        The pipeline that ran is recorded in the orthogonal ``ingest_mode`` field,
        which older entries simply lack.
        """
        formal_object = cls._formal_original_object(submit_file.file_id, chat_id, file_name)
        await minio_client.put_object(
            bucket_name=minio_client.bucket,
            object_name=formal_object,
            file=raw,
            content_type=cls._content_type_for(file_name),
        )

        entry: dict = {
            "file_id": submit_file.file_id,
            "original_filename": file_name,
            "relative_path": submit_file.relative_path,
            "parsing_status": "completed",
            "valid": True,
            "ingest_mode": "passthrough",
            # Not markdown, despite the name — see the key's docstring. It is the
            # workspace SEED object, and three downstream consumers key off it
            # (local prefetch, the workspace write below, the attachment drawer).
            "markdown_file_path": formal_object,
            "original_file_path": formal_object,
            # Set BEFORE the workspace write: that path only ``setdefault``s a 0
            # for non-markdown attachments, so a real count has to be there first.
            "line_count": cls._count_text_lines(raw),
            "image_count": 0,
        }
        if degraded_from is not None:
            entry["error_message"] = f"parse failed, original used directly: {degraded_from}"

        await cls._write_attachment_to_workspace(entry, chat_id, minio_client, as_markdown=False, used_names=used_names)

        # The raw track points at the same object as the reading track — that IS
        # what passthrough means. Mirroring it is load-bearing rather than
        # cosmetic: ``task_exec`` prefetches originals only for entries carrying
        # both keys, and lands them under ``uploads/`` — the exact path the
        # pointer block hands the model. Without the mirror the file would be
        # prefetched flat at the task-dir root and the advertised path would not
        # exist inside the code interpreter.
        entry["raw_filename"] = entry.get("markdown_filename")
        entry["raw_workspace_path"] = entry.get("workspace_path")
        return entry

    @staticmethod
    def _count_text_lines(raw: bytes) -> int:
        """Line count for the pointer block, tolerant of unknown encodings.

        Decoding with ``errors="replace"`` matches what ``WorkspaceBackend`` will
        do when the agent actually reads the file, so the advertised count and the
        readable content agree.
        """
        if not raw:
            return 0
        text = raw.decode("utf-8", errors="replace")
        return text.count("\n") + 1

    # Types that go into the workspace AS THEMSELVES — no parse attempted, the
    # original IS the workspace file. They are already in their final form: the
    # agent reads them with ``read_file`` and the code interpreter opens them with
    # pandas / json / whatever. Running them through the RAG pipeline would be a
    # lossy round-trip at best and, for everything the knowledge parser has no
    # loader for (.py, .json, …), a guaranteed exception whose only outcome is a
    # misleading "parse failed" chip.
    #
    # ``.env`` and ``.pkl`` are deliberately absent: the first would carry
    # credentials into the workspace and the model's context, the second is an
    # arbitrary-code deserialization vector.
    #
    # Keep in sync with the frontend accept list, ``client/src/common/chatAccept.ts``
    # (TASK_MODE_DATA_ACCEPT) — that file is what decides whether a user can pick
    # the file at all.
    _PASSTHROUGH_TEXT_EXTS = frozenset(
        {
            "txt", "csv", "tsv", "md", "markdown", "json", "jsonl", "xml", "html", "htm",
            "log", "yaml", "yml", "ini", "conf", "toml", "sql", "py", "js", "ts", "sh",
        }
    )  # fmt: skip

    # The overlap between "we could pass this through" and "the parser has a
    # loader for it", resolved in favour of parsing. This exists so the tie-break
    # is one greppable declaration instead of an implicit ordering between two
    # frozensets.
    #
    # Only html/htm qualify: stripping tags is a real conversion, and raw markup
    # is genuinely worse to read than the text inside it.
    #
    # Everything else that could be here is already in its final form, so parsing
    # can only subtract:
    #   - csv -> ``ExcelLoader`` is a RAG chunker (slices every ``data_rows``,
    #     repeats the header per chunk, hard-fails past a size ceiling). A csv is
    #     plain text that ``read_file`` reads directly, with offset/limit for a
    #     cheap peek at the head — the "reading view" it would build is a reshuffle
    #     of something already readable, stored twice.
    #   - txt/md -> the loader decodes, the splitter chunks, and the ingest rejoins
    #     the chunks with a blank line, so the file the model reads is not quite the
    #     file the user uploaded. The only thing it buys is encoding detection, and
    #     ``WorkspaceBackend`` already falls back to cchardet on read.
    _PARSE_WINS_EXTS = frozenset({"html", "htm"})

    # Types whose raw bytes are still worth carrying into the workspace after a
    # failed parse: text-like ones are directly readable via ``read_file``, and
    # _RAW_KEEP_EXTS / _IMAGE_EXTS have a consumer (code interpreter, image block).
    # Derived, not hand-maintained, so it can never drift from the routing sets.
    _TEXT_LIKE_EXTS = _PASSTHROUGH_TEXT_EXTS

    @classmethod
    def _ingest_route(cls, filename: str) -> str:
        """Decide how a submitted file enters the workspace.

        Returns one of:
          - ``"parse"``: run the knowledge ETL and write the markdown view
            (plus, for ``_RAW_KEEP_EXTS``, the original beside it).
          - ``"passthrough"``: skip the parser entirely; the original IS the
            workspace file.
          - ``"unsupported"``: no loader and no consumer — short-circuit instead
            of burning an ETL round-trip on a guaranteed failure.

        The order below is an explicit table rather than set precedence, because
        the sets genuinely overlap (csv is both passthrough-able and parseable)
        and an implicit ordering is exactly the kind of thing that silently
        inverts when someone adds a key to ``FileExtensionMap``.
        """
        from bisheng.knowledge.rag.base_file_pipeline import FileExtensionMap

        ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
        if ext in cls._PASSTHROUGH_TEXT_EXTS and ext not in FileExtensionMap:
            return "passthrough"
        if ext in cls._PASSTHROUGH_TEXT_EXTS:
            return "parse" if ext in cls._PARSE_WINS_EXTS else "passthrough"
        if ext in FileExtensionMap:
            return "parse"
        return "unsupported"

    @classmethod
    def _original_is_text(cls, filename: str) -> bool:
        """Whether an unparsed original is readable as text via ``read_file``."""
        ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
        return ext in cls._TEXT_LIKE_EXTS

    @classmethod
    def _original_is_usable(cls, filename: str) -> bool:
        """Whether an unparsed original has any consumer inside the workspace."""
        ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
        return ext in cls._TEXT_LIKE_EXTS or ext in cls._RAW_KEEP_EXTS or ext in cls._IMAGE_EXTS

    @classmethod
    async def _ingest_one_file(
        cls,
        submit_file: SubmitFileSchema,
        temp_info: dict | None,
        chat_id: str,
        minio_client,
        used_names: set[str] | None = None,
    ) -> dict:
        """Ingest a single submitted file into the session workspace.

        Idempotent on re-entry: a formal-bucket product produced earlier in this
        session is reused; the temp->formal copy is performed only once.
        """
        # Idempotency: reuse a formal-bucket product produced earlier this session.
        # A passthrough file has no markdown product, so its formal object keeps the
        # real extension — the drawer builds a preview URL straight off this key and
        # a ``.csv`` served as ``.md`` would be handed to the markdown renderer.
        is_passthrough = bool(temp_info) and temp_info.get("ingest_mode") == "passthrough"
        formal_object = (
            cls._formal_original_object(submit_file.file_id, chat_id, submit_file.file_name)
            if is_passthrough
            else cls._formal_markdown_object(submit_file.file_id, chat_id)
        )
        formal_exists = await minio_client.object_exists(bucket_name=minio_client.bucket, object_name=formal_object)

        if not formal_exists:
            if not temp_info or not temp_info.get("markdown_file_path"):
                # Temp metadata expired and no formal product: do not silently drop.
                logger.warning(
                    "linsight attachment %s (%s) has no formal product and expired temp metadata",
                    submit_file.file_id,
                    submit_file.file_name,
                )
                return {
                    "file_id": submit_file.file_id,
                    "original_filename": submit_file.file_name,
                    "relative_path": submit_file.relative_path,
                    "parsing_status": "expired",
                    "valid": False,
                    "error_message": "file metadata expired, please re-upload",
                }
            # First processing: copy temp -> formal bucket.
            await minio_client.copy_object(
                source_object=temp_info["markdown_file_path"],
                dest_object=formal_object,
                source_bucket=minio_client.tmp_bucket,
                dest_bucket=minio_client.bucket,
            )

        # Build the metadata entry (carry forward temp metadata when available).
        entry: dict = dict(temp_info) if temp_info else {}
        entry["file_id"] = submit_file.file_id
        entry.setdefault("original_filename", submit_file.file_name)
        # Always from THIS submission: temp_info is keyed by file_id and predates
        # the folder pick, so a stale value there must not win.
        entry["relative_path"] = submit_file.relative_path
        entry["parsing_status"] = "completed"
        entry["valid"] = True
        entry["markdown_file_path"] = formal_object

        # Promote the original image (parsed into tmp by _parse_file) to the formal
        # workspace bucket so the workspace previews the picture directly and
        # durably. Idempotent on resubmission.
        original_tmp = temp_info.get("original_file_path") if temp_info else None
        if original_tmp:
            ext = os.path.splitext(original_tmp)[1]
            formal_original = f"linsight/{chat_id}/{submit_file.file_id}_original{ext}"
            if not await minio_client.object_exists(bucket_name=minio_client.bucket, object_name=formal_original):
                await minio_client.copy_object(
                    source_object=original_tmp,
                    dest_object=formal_original,
                    source_bucket=minio_client.tmp_bucket,
                    dest_bucket=minio_client.bucket,
                )
            entry["original_file_path"] = formal_original

        if is_passthrough:
            # No markdown view exists: the original IS the workspace file, so it
            # keeps its real extension and doubles as its own raw track. See
            # ``_finalize_passthrough`` for why the mirror below is load-bearing.
            entry["original_file_path"] = formal_object
            await cls._write_attachment_to_workspace(
                entry, chat_id, minio_client, as_markdown=False, used_names=used_names
            )
            entry["raw_filename"] = entry.get("markdown_filename")
            entry["raw_workspace_path"] = entry.get("workspace_path")
            return entry

        # Write parsed markdown into the workspace (uploads/<name>.md).
        await cls._write_attachment_to_workspace(entry, chat_id, minio_client, used_names=used_names)
        return entry

    @staticmethod
    def _formal_markdown_object(file_id: str, chat_id: str) -> str:
        """Stable formal-bucket object key for a file's parsed markdown.

        Stable per (chat_id, file_id) so a resubmission of the same file_id maps
        to the same object and ``object_exists`` makes the copy idempotent.
        """
        return f"linsight/{chat_id}/{file_id}.md"

    @staticmethod
    def _formal_original_object(file_id: str, chat_id: str, filename: str) -> str:
        """Formal-bucket key for a PASSTHROUGH file — same slot, real extension.

        A passthrough file has no markdown product, so reusing the ``.md`` key
        above would serve a ``.csv`` under a ``.md`` name; the workspace panel
        builds its preview URL straight off this key and would hand it to the
        markdown renderer. Same stability property as the markdown key: one
        object per (chat_id, file_id), so re-submission stays idempotent.
        """
        ext = os.path.splitext(filename or "")[1].lower()
        return f"linsight/{chat_id}/{file_id}{ext}"

    @staticmethod
    async def _read_local_bytes(path: str) -> bytes | None:
        """Best-effort read of the transient local upload cache file.

        Returns ``None`` instead of raising: the original is a bonus track (code
        interpreter data / image preview), so losing it must never turn a file
        whose markdown parsed fine into a failed attachment.
        """
        try:
            return await asyncio.to_thread(lambda p: open(p, "rb").read(), path)
        except OSError:
            logger.warning("original bytes unavailable at {}; keeping only the parsed view", path)
            return None

    @classmethod
    def _should_keep_raw(cls, filename: str, local_path: str | None = None, size: int | None = None) -> bool:
        """Whether this upload's ORIGINAL bytes belong in the workspace too.

        Extension gate + size ceiling. When neither ``size`` nor a stat-able
        ``local_path`` is available the size check is skipped rather than
        failing closed — an un-measurable file is still worth carrying, and the
        ceiling exists to bound storage, not to gate correctness.
        """
        ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
        if ext not in cls._RAW_KEEP_EXTS:
            return False
        if size is None and local_path:
            try:
                size = os.path.getsize(local_path)
            except OSError:
                size = None
        if size is not None and size > cls._RAW_KEEP_MAX_BYTES:
            logger.info("skip carrying original {} into workspace: {} bytes exceeds ceiling", filename, size)
            return False
        return True

    @staticmethod
    def _safe_basename(original_filename: str) -> str:
        """Path-safe filename that PRESERVES the original (incl. non-ASCII) name.

        Only directory separators, traversal, and control characters are
        neutralized — the human-readable name (e.g. ``委托书.pdf``) is kept so
        ``ls`` shows a recognizable per-file entry instead of a generic
        ``file/index.md``. Returns ``"file"`` only if nothing usable remains.
        """
        import re

        base = (original_filename or "").strip()
        base = re.sub(r"[\x00-\x1f]+", "", base)  # control characters
        base = re.sub(r"[/\\]+", "_", base)  # path separators
        base = base.replace("..", "_").strip()  # path traversal
        return base or "file"

    @classmethod
    def _safe_relpath(cls, relative_path: str | None) -> str:
        """Sanitized DIRECTORY prefix for a folder-uploaded file, no trailing slash.

        ``年报/2024/Q1.xlsx`` -> ``年报/2024``. A plain upload (None/empty, or a
        bare file name) yields ``""``, which keeps the historical flat
        ``uploads/<name>`` layout untouched.

        This is the counterpart ``_safe_basename`` cannot be: that one collapses
        separators to ``_``, which is right for a file NAME and fatal for a folder
        upload. Traversal is neutralized the way ``skill_store._safe_rel_path``
        does it — every ``.`` / ``..`` / empty segment is dropped, so a crafted
        path cannot escape ``uploads/`` no matter what the client sends. Each
        surviving segment then goes through ``_safe_basename``, so control
        characters and stray separators are handled exactly as in file names.

        Depth is clamped defensively; ``_validate_folder_upload`` already rejects
        an over-deep batch outright, so clamping here is belt-and-braces rather
        than the user-facing rule.
        """
        raw = (relative_path or "").strip().replace("\\", "/")
        if not raw:
            return ""
        segments = [seg for seg in raw.split("/") if seg and seg not in (".", "..")]
        # The trailing segment is the file name — it is sanitized separately by the
        # caller and must never become a directory.
        dir_segments = segments[:-1][: cls._FOLDER_MAX_DEPTH]
        return "/".join(cls._safe_basename(seg) for seg in dir_segments)

    @classmethod
    def _validate_folder_upload(cls, files: list[SubmitFileSchema]) -> None:
        """Gate a folder upload on file count / total size / nesting depth.

        Only engages when at least one file carries a ``relative_path``; a plain
        multi-file selection stays unbounded, exactly as before.

        Rejection is all-or-nothing on purpose. Silently truncating to the first
        100 files would hand the user a workspace that looks complete and is not —
        the agent would summarize a partial folder without anyone noticing.
        """
        if not any((f.relative_path or "").strip() for f in files):
            return

        if len(files) > cls._FOLDER_MAX_FILES:
            raise LinsightFolderFileCountExceededError()

        total_bytes = sum(max(f.size or 0, 0) for f in files)
        if total_bytes > cls._FOLDER_MAX_TOTAL_BYTES:
            raise LinsightFolderTotalSizeExceededError()

        for file in files:
            raw = (file.relative_path or "").strip().replace("\\", "/")
            if not raw:
                continue
            segments = [seg for seg in raw.split("/") if seg and seg not in (".", "..")]
            # Directory levels only; the file name itself is not a level.
            if len(segments) - 1 > cls._FOLDER_MAX_DEPTH:
                raise LinsightFolderDepthExceededError()

    @staticmethod
    def _dedupe_workspace_name(rel_path: str, used_names: set[str] | None) -> str:
        """Make ``rel_path`` unique within one submission (append ``-2``, ``-3`` …).

        Without this, two distinct files sharing a workspace path would map to the
        same ``uploads/<path>`` key and the second would overwrite the first.

        The uniqueness namespace is the FULL relative path, so a folder upload
        keeps ``报告/summary.md`` and ``附件/summary.md`` side by side — only a real
        collision (same directory, same name) earns a suffix. The suffix always
        lands on the file name, never on a directory segment, so a directory named
        ``v1.2`` does not get its "extension" rewritten.
        """
        if used_names is None:
            return rel_path
        if rel_path not in used_names:
            used_names.add(rel_path)
            return rel_path
        dir_part, slash, filename = rel_path.rpartition("/")
        prefix = f"{dir_part}{slash}"
        stem, dot, ext = filename.rpartition(".")
        base = stem if dot else filename
        suffix = f".{ext}" if dot else ""
        i = 2
        while f"{prefix}{base}-{i}{suffix}" in used_names:
            i += 1
        unique = f"{prefix}{base}-{i}{suffix}"
        used_names.add(unique)
        return unique

    @classmethod
    async def _write_attachment_to_workspace(
        cls,
        entry: dict,
        chat_id: str,
        minio_client,
        *,
        as_markdown: bool = True,
        used_names: set[str] | None = None,
    ) -> None:
        """Write an attachment into the session workspace under its real filename.

        Workspace layout (design §9.3.2): ``workspace/{chat_id}/uploads/<name>``
          - parsed markdown   -> ``uploads/<original-stem>.md`` (as_markdown=True)
          - unconverted original -> ``uploads/<original-name>.<ext>`` (False)
          - **plus**, for ``_RAW_KEEP_EXTS`` that parsed fine, the ORIGINAL lands
            next to its markdown as ``uploads/<original-name>.<ext>``.

        Folder upload: when the entry carries a ``relative_path``, its directory
        part is rebuilt underneath ``uploads/`` — ``年报/2024/Q1.xlsx`` lands at
        ``uploads/年报/2024/Q1.md`` (+ the original beside it). The tree is the
        user's own organization of the material and often carries meaning the file
        names alone do not, so flattening it would lose information the agent needs.
        Everything downstream is already nesting-safe: ``WorkspaceBackend``
        read/write/ls/glob/grep, the local write-through cache, and the cross-round
        ``seed_workspace_from_previous`` copy.

        The dual-track write is deliberate: markdown is the model's reading view
        (``read_file``, token-cheap), the original is the tool's data
        (``bisheng_code_interpreter`` with pandas / python-docx / fitz). A
        spreadsheet flattened to markdown loses cell types, sheets and formulas —
        exactly what a user uploading a spreadsheet wants to compute on.

        The original filename (incl. non-ASCII) is preserved so ``ls`` shows a
        recognizable per-file name; same-name collisions are de-duplicated. Sets
        ``workspace_path`` / ``markdown_filename`` / ``line_count`` /
        ``image_count`` on ``entry`` for the pointer block + local prefetch, plus
        ``raw_workspace_path`` / ``raw_filename`` when an original was carried.
        """
        from bisheng.linsight.domain.services.workspace_backend import WORKSPACE_PREFIX

        safe = cls._safe_basename(entry["original_filename"])
        rel_dir = cls._safe_relpath(entry.get("relative_path"))
        if as_markdown:
            stem = safe.rsplit(".", 1)[0] if "." in safe else safe
            filename = f"{stem}.md"
        else:
            filename = safe
        filename = cls._dedupe_workspace_name(f"{rel_dir}/{filename}" if rel_dir else filename, used_names)
        rel_path = f"uploads/{filename}"
        object_key = f"{WORKSPACE_PREFIX}/{chat_id}/{rel_path}"

        # Read the stored product (formal bucket) and write it into the workspace.
        file_bytes = await minio_client.get_object(
            bucket_name=minio_client.bucket, object_name=entry["markdown_file_path"]
        )
        if file_bytes is None:
            file_bytes = b""
        await minio_client.put_object(
            bucket_name=minio_client.bucket,
            object_name=object_key,
            file=file_bytes,
            # An unparsed original keeps its real type too, so the attachment chip
            # and any download serve it as what it is.
            content_type="text/markdown" if as_markdown else cls._content_type_for(filename),
        )

        entry["workspace_path"] = f"/{rel_path}"
        entry["markdown_filename"] = filename
        if as_markdown:
            text = file_bytes.decode("utf-8", errors="replace")
            entry["line_count"] = entry.get("line_count") or (text.count("\n") + 1 if text else 0)
        else:
            entry.setdefault("line_count", 0)
        entry["image_count"] = entry.get("image_count", 0)

        if as_markdown:
            await cls._write_raw_original_to_workspace(entry, chat_id, minio_client, safe, used_names)

    @classmethod
    async def _write_raw_original_to_workspace(
        cls,
        entry: dict,
        chat_id: str,
        minio_client,
        safe_name: str,
        used_names: set[str] | None,
    ) -> None:
        """Second track: copy the ORIGINAL next to its markdown view.

        No-op unless the type is worth keeping raw AND an original was persisted
        upstream (``entry["original_file_path"]``, set by ``_parse_file`` /
        ``_ingest_daily_file``). Best-effort: a failure here must never sink an
        attachment whose markdown view already landed — the task stays usable,
        just without the precise-data track.

        The original lands in the SAME directory as its markdown view, folder
        upload included (``uploads/年报/2024/Q1.xlsx`` next to ``…/Q1.md``), because
        ``prepare_file_list`` hands the model the raw path relative to the code
        interpreter's working directory and the local prefetch mirrors that layout.
        """
        from bisheng.linsight.domain.services.workspace_backend import WORKSPACE_PREFIX

        original_object = entry.get("original_file_path")
        if not original_object or not cls._should_keep_raw(entry.get("original_filename", "")):
            return

        try:
            raw_bytes = await minio_client.get_object(bucket_name=minio_client.bucket, object_name=original_object)
            if not raw_bytes:
                logger.warning("original {} is empty/missing; workspace keeps only the markdown view", original_object)
                return

            rel_dir = cls._safe_relpath(entry.get("relative_path"))
            raw_filename = cls._dedupe_workspace_name(f"{rel_dir}/{safe_name}" if rel_dir else safe_name, used_names)
            rel_path = f"uploads/{raw_filename}"
            content_type = cls._content_type_for(raw_filename)
            await minio_client.put_object(
                bucket_name=minio_client.bucket,
                object_name=f"{WORKSPACE_PREFIX}/{chat_id}/{rel_path}",
                file=raw_bytes,
                content_type=content_type,
            )
            entry["raw_workspace_path"] = f"/{rel_path}"
            entry["raw_filename"] = raw_filename
        except Exception:
            logger.exception("failed to carry original {} into workspace {}", original_object, chat_id)

    # Chat titles live in message_session.name (VARCHAR(255)); a reasoning model
    # can emit far more than a title (a whole <think> block), so clamp the length.
    _TITLE_MAX_CHARS = 50
    _FALLBACK_TITLE = "New Chat"

    @classmethod
    def _normalize_title(cls, content: Any, question: str) -> str:
        """Turn a raw title-model response into a clean, storable title.

        Reasoning models (e.g. qwen3.5) inline ``<think>...</think>`` into the
        content — strip the block, keep the first line, clamp the length. If
        nothing usable survives (empty content / pure reasoning), fall back to a
        slice of the user's question so the session isn't stuck on "New Chat".
        """
        title = strip_think_block(str(content or ""))
        title = title.splitlines()[0].strip() if title else ""
        title = title[: cls._TITLE_MAX_CHARS]
        return title or cls._fallback_title(question)

    @classmethod
    def _fallback_title(cls, question: str) -> str:
        """A meaningful placeholder derived from the user's question."""
        head = (question or "").strip()
        head = head.splitlines()[0].strip() if head else ""
        return head[: cls._TITLE_MAX_CHARS] or cls._FALLBACK_TITLE

    @classmethod
    async def task_title_generate(cls, question: str, chat_id: str, login_user: UserPayload) -> dict:
        """
        Generate task title

        Args:
            question: User Questions
            chat_id: SessionsID
            login_user: Logged in user information

        Returns:
            Dictionary with task title
        """
        try:
            llm, _ = await cls._get_llm(login_user.user_id)

            # Buatprompt
            prompt = await cls._generate_title_prompt(question)

            # Generate task title
            task_title = await llm.ainvoke(prompt)

            # Clean reasoning-model <think> noise + clamp; falls back to the
            # question when the model returns nothing usable (see _normalize_title).
            title = cls._normalize_title(getattr(task_title, "content", None), question)

            # Update session title
            await cls._update_session_title(chat_id, title)

            return {"task_title": title, "chat_id": chat_id, "error_message": None}

        except Exception as e:
            logger.exception("Failed to generate task title")
            # Even on hard failure, seed a question-based title so the session
            # isn't stuck on the "New Chat" placeholder (best-effort write).
            fallback = cls._fallback_title(question)
            try:
                await cls._update_session_title(chat_id, fallback)
            except Exception:
                logger.exception("Failed to write fallback task title")
            return {"task_title": fallback, "chat_id": chat_id, "error_message": str(e)}

    @classmethod
    async def _get_workbench_config(cls):
        """Get and validate the workbench configuration"""
        workbench_conf = await LLMService.get_workbench_llm()
        if not workbench_conf or not workbench_conf.linsight_default_model_id:
            raise cls.BishengLLMError(
                "The task has been terminated, please contact the administrator to check the status of the Ideas task execution model"
            )
        return workbench_conf

    @classmethod
    async def _generate_title_prompt(cls, question: str) -> list[tuple[str, str]]:
        """Generate Title Generateprompt"""
        prompt_service = await get_prompt_manager()
        prompt_obj = prompt_service.render_prompt(namespace="gen_title", prompt_name="linsight", USER_GOAL=question)
        return [("system", prompt_obj.prompt.system), ("user", prompt_obj.prompt.user)]

    @classmethod
    async def _update_session_title(cls, chat_id: str, title: str) -> None:
        """Update session title"""
        session = await MessageSessionDao.async_get_one(chat_id)
        if session:
            await MessageSessionDao.update_session_name(chat_id, title)

    @classmethod
    async def get_linsight_session_version_list(cls, session_id: str) -> list[LinsightSessionVersion]:
        """
        Get a list of Invisible Conversation Versions

        Args:
            session_id: SessionsID

        Returns:
            Inspiration Session Version List
        """
        return await LinsightSessionVersionDao.get_session_versions_by_session_id(session_id)

    @classmethod
    async def prepare_file_list(
        cls, session_version: LinsightSessionVersion, has_code_interpreter: bool = False
    ) -> list[str]:
        """Prepare the zero-body ``<uploaded_files>`` pointer block (design §9.3.3).

        Each valid attachment becomes a pointer item (path + name + lines +
        images) — **no file body or preview** is injected, preserving the
        offload-first contract (the model reads bodies on demand via
        ``read_file``). Attachments with no workspace object at all (expired
        metadata) are skipped; ones that failed to parse but left their original
        behind ARE announced, so the model does not meet an unreadable binary via
        ``ls`` and try to ``read_file`` it.

        Folder upload changes the rendering, not the contract: pointers are grouped
        under their directory, and past ``_FILE_LIST_MAX_ITEMS`` attachments the
        block degrades to a per-directory summary that hands the model ``ls`` /
        ``glob`` instead of a hundred pointer lines. A flat submission renders
        exactly as it always did.

        Args:
            has_code_interpreter: whether the sandboxed code interpreter is bound
                this run. Gates the "open the original with Python" guidance —
                naming a tool that is not bound is the same class of bug as the
                ``search_knowledge_base`` prompt/tool mismatch.

        Returns:
            A single-element list holding the ``<uploaded_files>`` block, or an
            empty list when there are no valid attachments. (A list is returned
            for parity with ``parse_file_list_str`` which joins on newlines.)
        """
        if not session_version.files:
            return []

        # (directory, rendered pointer, display name) per announced attachment.
        # The directory comes from the FOLDER-UPLOAD relative path, never from
        # parsing ``workspace_path`` — the legacy ``/uploads/<name>/index.md``
        # fallback shape would otherwise read as a directory that does not exist.
        records: list[tuple[str, str, str]] = []
        has_raw = False
        has_passthrough = False
        has_unparsed = False
        has_media = False
        for file in session_version.files:
            path = file.get("workspace_path") or f"/uploads/{file.get('file_id')}/index.md"
            name = file.get("original_filename", "")
            rel_dir = cls._safe_relpath(file.get("relative_path"))

            if file.get("valid") is False:
                # Previously skipped outright, which left the model to discover the
                # file via ``ls`` with no idea it is an unparsed binary — it would
                # then ``read_file`` it and blow up the task. Announce it instead,
                # with the one route that actually works.
                if not file.get("workspace_path"):
                    # No workspace object at all. An unsupported type (mp3/mp4/zip)
                    # is deliberately not carried in, but staying silent about it
                    # means the user sees their attachment accepted while the model
                    # never hears of it. Expired metadata stays skipped — there is
                    # nothing to say beyond "re-upload", which the chip already says.
                    if file.get("parsing_status") == "unsupported":
                        records.append(
                            (rel_dir, f"- name: {name}\n  note: 该格式无法解析，也无法在工作区中读取，本次不可用", name)
                        )
                    continue
                has_unparsed = True
                records.append(
                    (
                        rel_dir,
                        f"- path: {path}\n  name: {name}\n  note: 解析失败，工作区只有二进制原件（不可 read_file）",
                        name,
                    )
                )
                continue

            item = "- path: {path}\n  name: {name}\n  lines: {lines}\n  images: {images}".format(
                path=path,
                name=name,
                lines=file.get("line_count", 0),
                images=file.get("image_count", 0),
            )
            raw_path = file.get("raw_workspace_path")
            if raw_path:
                # A passthrough file mirrors its own path into the raw track, so
                # ``path == raw``. Counting that as ``has_raw`` would trigger the
                # dual-track wording ("raw holds the precise data, do not read_file
                # it") about a file whose raw track is plain text the model should
                # absolutely read.
                if file.get("ingest_mode") == "passthrough":
                    has_passthrough = True
                else:
                    has_raw = True
                # Rendered RELATIVE on purpose. The code interpreter resolves paths
                # against its working directory (the local task dir / sandbox root),
                # where the original lives at ``uploads/<name>``; a leading slash
                # would send it to the filesystem root and fail.
                item += f"\n  raw: {raw_path.lstrip('/')}"
            if cls._is_media_filename(name):
                has_media = True
                item += "\n  note: 音视频已 ASR 转写；path 为转写文本（.md），name 为原始上传文件名（非扩展名错误）"
            records.append((rel_dir, item, name))

        if not records:
            return []

        header_parts: list[str] = []
        has_folder = any(rel_dir for rel_dir, _, _ in records)
        if has_folder:
            header_parts.append(
                "说明（文件夹）：本次上传包含目录结构，下方按目录分组。目录层级是用户自己的组织方式，"
                "常常带有分类/时间/版本等含义，理解与产出时请保留这一结构。"
                '需要进一步定位时用 ls("/uploads/<目录>") 或 glob（如 "/uploads/**/*.xlsx"），不要假设文件不存在。\n'
            )
        if has_media:
            header_parts.append(
                "说明（音视频）：<uploaded_files> 中 name 为 .mp3/.mp4 等原始上传名，"
                "path 为平台 ASR 转写后的 .md 文本视图。请 read_file(path) 获取语音/视频内容；"
                "这不是扩展名标注错误或误命名，勿在回复中声称「实际是文本文件」。\n"
            )
        # One ``说明：`` paragraph assembled from independent clauses, rather than a
        # block per file kind. The kinds co-occur freely (a dual-track xlsx, a
        # passthrough csv and a broken pdf in one submission), and a paragraph each
        # would both bloat the prompt and contradict itself — the dual-track wording
        # ends in "do not read_file the original", which is exactly wrong for a
        # passthrough file whose original is the text.
        has_binary_original = has_raw or has_unparsed
        detail_parts: list[str] = []
        if has_raw:
            detail_parts.append(
                "path 指向可直接 read_file 的文本视图；raw 指向同名原件"
                "（表格/文档的精确数据、单元格、样式、页面结构都在原件里）。"
            )
        if has_passthrough:
            detail_parts.append(
                "部分条目的 path 与 raw 指向同一个文本原件（.csv/.py/.json 等）——"
                "它本身就是最终格式，read_file 与代码工具都可直接使用，不必再去找「解析后的版本」。"
            )
        if has_unparsed:
            detail_parts.append("标注「解析失败」的条目在工作区只有二进制原件，不可 read_file。")
        if has_binary_original:
            if has_code_interpreter:
                detail_parts.append(
                    "需要精确数值或做数据分析时，用 bisheng_code_interpreter 读原件"
                    "（Excel 用 pandas/openpyxl，Word 用 python-docx，PDF 用 fitz），不要 read_file 二进制原件。"
                    "raw 是相对当前工作目录的路径，在代码里直接用该相对路径打开。"
                )
            else:
                # No code interpreter this run: the binary original is unusable, so
                # do not send the model chasing it. Say what it CAN do instead.
                detail_parts.append(
                    "本次没有可用的代码执行工具，无法读取二进制原件——请基于文本视图作答，"
                    "并在结论中说明受原件格式限制的部分。"
                )
        elif has_passthrough and has_code_interpreter:
            detail_parts.append("raw 是相对当前工作目录的路径，在代码里直接用该相对路径打开。")
        if detail_parts:
            header_parts.append("说明：" + "".join(detail_parts) + "\n")
        header = "".join(header_parts)

        if len(records) > cls._FILE_LIST_MAX_ITEMS:
            body = cls._render_upload_dir_summary(records)
        else:
            body = cls._render_upload_pointers(records, grouped=has_folder)

        block = "<uploaded_files>\n" + header + body + "\n</uploaded_files>"
        return [block]

    # Past this many attachments a per-file pointer list stops being an index and
    # starts being noise that crowds out the user's actual question. A folder
    # upload is capped at _FOLDER_MAX_FILES, so the summary mode below is what a
    # large folder actually renders as.
    _FILE_LIST_MAX_ITEMS = 40

    @staticmethod
    def _group_upload_records(records: list[tuple[str, str, str]]) -> dict[str, list[tuple[str, str]]]:
        """Group ``(dir, pointer, name)`` by directory, preserving first-seen order."""
        grouped: dict[str, list[tuple[str, str]]] = {}
        for rel_dir, text, name in records:
            grouped.setdefault(rel_dir, []).append((text, name))
        return grouped

    @classmethod
    def _render_upload_pointers(cls, records: list[tuple[str, str, str]], *, grouped: bool) -> str:
        """Full per-file pointer list, optionally grouped under directory headings."""
        if not grouped:
            return "\n".join(text for _, text, _ in records)

        chunks: list[str] = []
        for rel_dir, entries in cls._group_upload_records(records).items():
            heading = f"[目录] /uploads/{rel_dir}/" if rel_dir else "[目录] /uploads/"
            chunks.append(heading + "\n" + "\n".join(text for text, _ in entries))
        return "\n".join(chunks)

    @classmethod
    def _render_upload_dir_summary(cls, records: list[tuple[str, str, str]]) -> str:
        """Directory-level summary used when the per-file list would be too long.

        Emits one entry per directory with a file count and an extension
        breakdown, and points the model at ``ls`` / ``glob`` for the actual names.
        The pointer block is an index, not the data — the model reads bodies on
        demand either way, so a summary loses nothing but the token cost.
        """
        lines: list[str] = []
        total = 0
        for rel_dir, entries in cls._group_upload_records(records).items():
            total += len(entries)
            ext_counts: dict[str, int] = {}
            for _, name in entries:
                ext = os.path.splitext(name or "")[1].lower().lstrip(".") or "无扩展名"
                ext_counts[ext] = ext_counts.get(ext, 0) + 1
            types = "、".join(f"{ext}×{count}" for ext, count in sorted(ext_counts.items(), key=lambda kv: -kv[1]))
            path = f"/uploads/{rel_dir}/" if rel_dir else "/uploads/"
            lines.append(f"- dir: {path}\n  files: {len(entries)}\n  types: {types}")
        lines.append(
            f"共 {total} 个文件，数量较多，此处只列目录概览。"
            '用 ls("/uploads/<目录>") 列出具体文件名，用 glob（如 "/uploads/**/*.xlsx"）按类型定位，'
            "再对需要的文件 read_file。"
        )
        return "\n".join(lines)

    @classmethod
    async def prepare_knowledge_list(cls, knowledge_list: list[KnowledgeRead]) -> list[str]:
        """Render each available KB as a clean, readable prompt line that clearly
        exposes its ``knowledge_id`` so the agent's ``search_knowledge_base`` tool
        can target a real id. One item per KB: name + id (+ optional description).
        Private KBs use a generic name to avoid leaking their titles."""
        res = []
        if not knowledge_list:
            return res
        for one in knowledge_list:
            name = "个人知识库" if one.type == KnowledgeTypeEnum.PRIVATE.value else one.name
            line = f"- {name} (knowledge_id: {one.id})"
            if one.type != KnowledgeTypeEnum.PRIVATE.value and one.description:
                line += f": {one.description}"
            res.append(line)
        return res

    @classmethod
    async def get_execute_task_detail(cls, session_version_id: str, login_user: UserPayload | None = None):
        """
        Get task execution details

        Args:
            session_version_id: Inspiration Conversation VersionID
            login_user: Logged in user information

        Returns:
            Execute Task Detail List
        """
        execute_tasks = await LinsightExecuteTaskDao.get_by_session_version_id(session_version_id)

        if not execute_tasks:
            return []

        # F035 problem 2: the session-level pseudo task (task_data.is_session_global)
        # carries planning/wrap-up/direct-answer steps. Drop it when it captured no
        # steps so we never render an empty "执行准备" node.
        def _is_session_global(task: Any) -> bool:
            return bool((task.task_data or {}).get("is_session_global"))

        execute_tasks = [t for t in execute_tasks if not (_is_session_global(t) and not t.history)]
        if not execute_tasks:
            return []

        # 1. Get Level 1 Tasks parent_task_id Yes  None Task
        root_tasks = [task for task in execute_tasks if task.parent_task_id is None]

        # 2. accordingprevious_task_idAND:next_task_idSort first level tasks
        def sort_tasks_by_chain(tasks: list[Any]) -> list[Any]:
            """
            Sort task list by task chain
            previous_task_idYes Noneis the first task,next_task_idYes Noneis the last task.
            """
            if not tasks:
                return []

            # Create a task dictionary for quick lookups
            task_dict = {task.id: task for task in tasks}

            # Find the start node of the chain (previous_task_id are None）
            start_tasks = [task for task in tasks if task.previous_task_id is None]

            sorted_tasks = []

            for start_task in start_tasks:
                # Build task chains from each start node
                current_task = start_task
                chain = []

                while current_task is not None:
                    chain.append(current_task)
                    # Setujunext_task_idFind next task
                    next_task_id = current_task.next_task_id
                    current_task = task_dict.get(next_task_id) if next_task_id else None

                sorted_tasks.extend(chain)

            # Dealing with possible orphaned tasks (neitherpreviousNothing, either!nextpointing to them)
            processed_ids = {task.id for task in sorted_tasks}
            orphan_tasks = [task for task in tasks if task.id not in processed_ids]
            sorted_tasks.extend(orphan_tasks)

            return sorted_tasks

        # Sort first level tasks
        sorted_root_tasks = sort_tasks_by_chain(root_tasks)
        # Surface the session-global pseudo task first (planning precedes the
        # planned sub-tasks). Stable sort keeps the rest of the chain order.
        sorted_root_tasks = sorted(sorted_root_tasks, key=lambda t: 0 if _is_session_global(t) else 1)

        # 3. Build task tree Use parent_task_id Associate subtasks with parent tasks
        def build_task_tree(parent_tasks: list[Any], all_tasks: list[Any]) -> list[TaskNode]:
            """
            Build task tree
            """
            # Create task mapping
            task_map = {task.id: task for task in all_tasks}

            # By Parent TaskIDGroup subtasks
            children_map = {}
            for task in all_tasks:
                if task.parent_task_id:
                    if task.parent_task_id not in children_map:
                        children_map[task.parent_task_id] = []
                    children_map[task.parent_task_id].append(task)

            def build_node(task: Any) -> TaskNode:
                """Recursively build task nodes"""
                node = TaskNode(task=task)

                # Get subtasks
                child_tasks = children_map.get(task.id, [])

                # Sort subtasks
                sorted_child_tasks = sort_tasks_by_chain(child_tasks)

                # Recursively build child nodes
                for child_task in sorted_child_tasks:
                    child_node = build_node(child_task)
                    node.children.append(child_node)

                return node

            # Build Root Node List
            root_nodes = []
            for parent_task in parent_tasks:
                root_node = build_node(parent_task)
                root_nodes.append(root_node)

            return root_nodes

        # Build task tree
        task_tree = build_task_tree(sorted_root_tasks, execute_tasks)

        # 4. Returns the root node list of the task tree
        result = [node.to_dict() for node in task_tree]

        return result

    @classmethod
    async def upload_file(cls, file: UploadFile) -> dict:
        """
        Upload files to the Inspiration Workbench

        Args:
            file: files uploaded

        Returns:
            File Information Dictionary
        """
        from bisheng.knowledge.domain.upload_file_size import get_max_upload_bytes

        # url <g id="Bold">Code</g> decode The file name
        original_filename = unquote(file.filename)

        # Per-file ceiling, shared with the knowledge upload path so documents and
        # media keep their (configurable) separate limits. Task mode had no
        # server-side size check at all — tolerable while files arrived one at a
        # time, not once a folder upload sends a hundred in one go.
        if file.size is not None and file.size > get_max_upload_bytes(original_filename):
            raise LinsightFileTooLargeError()

        # Generate file information
        file_id = uuid.uuid4().hex[:8]  # Buat8Bit Unique FileID
        file_extension = original_filename.split(".")[-1] if "." in original_filename else ""
        unique_filename = f"{file_id}.{file_extension}"

        # Save file
        file_path = await save_file_to_folder(file, "linsight", unique_filename)

        upload_result = {
            "file_id": file_id,
            "filename": unique_filename,
            "original_filename": original_filename,
            "file_path": file_path,
            "parsing_status": "running",
        }

        # Cache Result
        await cls._cache_parse_result(file_id, upload_result)

        return upload_result

    @classmethod
    async def parse_file(cls, upload_result: dict, invoke_user_id: int) -> dict:
        """
        Parsing uploaded files

        Args:
            upload_result: Upload results
            invoke_user_id: Call UserID

        Returns:
            Parsing results
        """
        logger.info(f"Start parsing files: {upload_result}")

        file_id = upload_result["file_id"]
        original_filename = upload_result["original_filename"]
        file_path = upload_result["file_path"]
        try:
            # Asynchronous execution of file parsing
            parse_result = await cls._parse_file(invoke_user_id, file_id, file_path, original_filename)

            # Cache Result
            await cls._cache_parse_result(file_id, parse_result)

            logger.info(f"File analysis complete: {parse_result}")
        except Exception as e:
            logger.error(f"File parsing failed: file_id={file_id}, error={e!s}")
            parse_result = {
                "file_id": file_id,
                "original_filename": original_filename,
                "parsing_status": "failed",
                "error_message": str(e),
            }
            await cls._cache_parse_result(file_id, parse_result)

        return parse_result

    @classmethod
    async def _parse_file(
        cls,
        invoke_user_id: int,
        file_id: str,
        file_path: str,
        original_filename: str,
    ) -> dict:
        """
        Synchronize parsed files

        Parses the upload into markdown and uploads that markdown to MinIO so the
        execution agent can read it from its workspace (``read_file``). The file is
        intentionally NOT vectorised into milvus/es: task execution reads the full
        markdown directly, so the old ``col_linsight_file_*`` vectors are unused.

        Args:
            file_id: Doc.ID
            file_path: FilePath
            original_filename: Original Filename

        Returns:
            Parsing results
        """
        # Read file contents
        try:
            from bisheng.api.v1.schemas import FileProcessBase
            from bisheng.knowledge.rag.temp_file_pipeline import TempFilePipeline

            # Passthrough types never reach the parser. This branch matters more
            # here than on the daily path: a parse failure is reported to the
            # follow-up input as ``failed``, and that input DELETES the attachment
            # from the box on sight — so without this a ``.py`` could not even be
            # submitted, let alone used.
            if cls._ingest_route(original_filename) == "passthrough":
                raw_bytes = await cls._read_local_bytes(file_path)
                if raw_bytes is not None:
                    minio_client = await get_minio_storage()
                    tmp_key = f"{file_id}{os.path.splitext(original_filename)[1].lower()}"
                    await minio_client.put_object_tmp(tmp_key, raw_bytes)
                    return {
                        "file_id": file_id,
                        "original_filename": original_filename,
                        "parsing_status": "completed",
                        "ingest_mode": "passthrough",
                        "parse_type": "passthrough",
                        "markdown_filename": tmp_key,
                        "markdown_file_path": tmp_key,
                        "markdown_file_md5": await async_calculate_md5(raw_bytes),
                        # Counted here, where the bytes are already in hand. The
                        # workspace write only ``setdefault``s a 0 for non-markdown
                        # attachments, so a real count has to arrive before it.
                        "line_count": cls._count_text_lines(raw_bytes),
                        # Deliberately no ``original_file_path``: ingest promotes
                        # this same key to the formal bucket, and setting it would
                        # make it store a second copy of identical bytes.
                    }
                # Unreadable local cache file: fall through to the parser so the
                # failure is reported through the one existing path.

            file_rule = FileProcessBase(
                knowledge_id=0,
                separator=["\n\n", "\n"],
                separator_rule=["after", "after"],
                chunk_size=1000,
                chunk_overlap=100,
            )
            pipeline = TempFilePipeline(
                invoke_user_id=invoke_user_id,
                local_file_path=file_path,
                file_name=original_filename,
                file_rule=file_rule,
            )
            result = await pipeline.arun()
            texts = [doc.page_content for doc in result.documents]
            parse_type = type(pipeline.loader).__name__ if pipeline.loader else "local"

            # BuatmarkdownContents
            markdown_content = "\n".join(texts)
            markdown_bytes = markdown_content.encode("utf-8")

            # SAVINGmarkdownDoc.
            markdown_filename = f"{file_id}.md"
            minio_client = await get_minio_storage()
            await minio_client.put_object_tmp(markdown_filename, markdown_bytes)
            markdown_md5 = await async_calculate_md5(markdown_bytes)

            result = {
                "file_id": file_id,
                "original_filename": original_filename,
                "parsing_status": "completed",
                "parse_type": parse_type,
                "markdown_filename": markdown_filename,
                "markdown_file_path": markdown_filename,
                "markdown_file_md5": markdown_md5,
            }

            # The original bytes only exist as a transient LOCAL cache file at this
            # point (``save_file_to_folder`` writes to CACHE_DIR, which the Linsight
            # worker process cannot reach), so persist them to the tmp bucket now and
            # carry the key forward; ingest promotes it to the formal bucket. Two
            # distinct reasons to keep an original:
            #   - images  -> the attachment chip previews the picture, not its caption;
            #   - _RAW_KEEP_EXTS -> the workspace carries the original next to the .md
            #     so the code interpreter can compute on real data (design: md is the
            #     model's reading view, the original is the tool's data).
            ext = os.path.splitext(original_filename)[1].lower().lstrip(".")
            if ext in cls._IMAGE_EXTS or cls._should_keep_raw(original_filename, file_path):
                raw_bytes = await cls._read_local_bytes(file_path)
                if raw_bytes:
                    original_tmp_key = f"{file_id}_original.{ext}"
                    await minio_client.put_object_tmp(original_tmp_key, raw_bytes)
                    result["original_file_path"] = original_tmp_key

            return result
        except Exception as e:
            logger.error(f"File parsing failed: file_id={file_id}, error={e!s}")
            return {
                "file_id": file_id,
                "original_filename": original_filename,
                "parsing_status": "failed",
                "error_message": str(e),
            }

    @classmethod
    async def _cache_parse_result(cls, file_id: str, parse_result: dict) -> None:
        """Cache Result"""
        redis_client = await get_redis_client()
        key = f"{cls.FILE_INFO_REDIS_KEY_PREFIX}{file_id}"
        await redis_client.aset(key=key, value=parse_result, expiration=60 * 60 * cls.CACHE_EXPIRATION_HOURS)

    @classmethod
    async def _init_bisheng_code_tool(
        cls, selected_tool_ids: list[int], file_dir: str, user_id: int, session_version_id: str | None = None
    ) -> list[BaseTool]:
        """Initialize the code interpreter separately (it needs the workspace dir bound).

        ``selected_tool_ids`` is the user's per-turn tool selection. The id is
        consumed (removed) on a hit so the generic ``init_by_tool_ids`` pass does
        not build a second, workspace-less copy of the same tool.
        """
        tools = []
        bisheng_code_tool = await GptsToolsDao.aget_tool_by_tool_key(tool_key="bisheng_code_interpreter")
        if not bisheng_code_tool or bisheng_code_tool.id not in selected_tool_ids:
            return tools
        # Individual initialization code interpreter tool
        selected_tool_ids.remove(bisheng_code_tool.id)
        code_config = json.loads(bisheng_code_tool.extra) if bisheng_code_tool.extra else {}
        if "config" not in code_config:
            code_config["config"] = {}
        if "local" not in code_config["config"]:
            code_config["config"]["local"] = {}
        code_config["config"]["local"]["local_sync_path"] = file_dir
        if session_version_id:
            from bisheng.linsight.domain.services.workspace_backend import WORKSPACE_PREFIX

            # Lets the executor mirror what it writes into ``workspace/<svid>/``.
            # Without it the local working dir is the ONLY copy, so the file tools
            # cannot see a code-generated deliverable and the next turn's
            # seed-from-previous finds an empty ``output/``.
            code_config["config"]["local"]["workspace_prefix"] = f"{WORKSPACE_PREFIX}/{session_version_id}"
        if "e2b" not in code_config["config"]:
            code_config["config"]["e2b"] = {}
        code_config["config"]["e2b"]["local_sync_path"] = file_dir
        # Default60Validity period of minutes
        code_config["config"]["e2b"]["timeout"] = 3600
        code_config["config"]["e2b"]["keep_sandbox"] = True
        # ``file_list`` is the E2B copy-in set: E2bCodeExecutor.__init__ reads every
        # entry fully into worker memory and pushes it into the sandbox up front.
        # E2B's own contract caps that at SIZE_AUTOPUSH — anything larger is meant to
        # be requested explicitly per run — while the dual-track ingest keeps
        # originals up to _RAW_KEEP_MAX_BYTES (50MB), which LocalExecutor serves for
        # free through local_sync_path. Filter here so the E2B ceiling is honoured
        # without shrinking what the local executor can reach.
        file_list = []
        oversized: list[str] = []
        for root, dirs, files in os.walk(file_dir):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    if os.path.getsize(file_path) > SIZE_AUTOPUSH:
                        oversized.append(file_path)
                        continue
                except OSError:
                    # Unstattable file: let it through rather than silently dropping
                    # it — the push itself will surface any real problem.
                    pass
                file_list.append(WriteEntry(data=file_path, path=file_path.replace(file_dir, ".")))
        if oversized:
            # Never let a bounded copy-in look complete: the model is told these
            # paths exist, so a silent drop reads as "the tool is broken".
            logger.warning(
                "code interpreter: {} file(s) exceed the E2B auto-push ceiling ({} bytes) and were not "
                "pushed into the sandbox: {}",
                len(oversized),
                SIZE_AUTOPUSH,
                ", ".join(os.path.basename(p) for p in oversized),
            )
        code_config["config"]["e2b"]["file_list"] = file_list

        bisheng_code_tool.extra = code_config

        tools = await ToolExecutor.init_by_tool_id(
            tool=bisheng_code_tool,
            app_id=ApplicationTypeEnum.LINSIGHT.value,
            app_name=ApplicationTypeEnum.LINSIGHT.value,
            app_type=ApplicationTypeEnum.LINSIGHT,
            user_id=user_id,
        )
        return [tools]

    @classmethod
    async def init_linsight_config_tools(
        cls, session_version: LinsightSessionVersion, llm: BishengLLM, need_upload: bool = False, file_dir: str = None
    ) -> list[BaseTool]:
        """
        Tools for initializing Invis configurations

        Args:
            session_version: Session Version Model
            llm: LLMInstances
            need_upload: Do I need to bind a user-uploaded file to the code interpreter?
            file_dir: Root directory for user uploaded files

        Returns:
            Tools List
        """
        tools = []

        if not session_version.tools:
            return tools

        # &Extraction toolID
        tool_ids = list(dict.fromkeys(cls._extract_tool_ids(session_version.tools)))  # de-dup, preserve order

        # todo Better tool initialization scheme
        # The code interpreter binds ONLY when the user picked it for this turn.
        # It used to be gated on the daily-config whitelist (the admin-configured
        # candidate list), which made it bind on every task turn regardless of the
        # input-bar toggle — the whitelist is the set of tools a user MAY pick,
        # not a set of tools to auto-enable.
        if need_upload and file_dir:
            try:
                bisheng_code_tool = await cls._init_bisheng_code_tool(
                    tool_ids,
                    file_dir,
                    user_id=session_version.user_id,
                    session_version_id=session_version.id,
                )
                tools.extend(bisheng_code_tool)
            except Exception:
                # Swallowing is deliberate (a broken tool must not kill the task),
                # but it must stay diagnosable: logger.error(f"...{e!s}") dropped the
                # traceback, so a run silently losing the code interpreter looked
                # identical whether the cause was a permission gate, a bad config or
                # a missing sandbox. logger.exception keeps the stack.
                logger.exception(
                    "Failed to initialize BiSheng code interpreter tool: session_version_id={}",
                    session_version.id,
                )

        # Unified-resource direction (2026-06-16): task mode reuses the daily
        # tool selection directly. Every selected tool id (a real GptsTools id
        # the user already has access to) binds. The code interpreter is already
        # consumed above when selected, so it is never built twice.
        valid_tool_ids = tool_ids

        # Initialization Tools
        if valid_tool_ids:
            tools.extend(
                await ToolExecutor.init_by_tool_ids(
                    valid_tool_ids,
                    app_id=ApplicationTypeEnum.LINSIGHT.value,
                    app_name=ApplicationTypeEnum.LINSIGHT.value,
                    app_type=ApplicationTypeEnum.LINSIGHT,
                    user_id=session_version.user_id,
                )
            )

        return tools

    @classmethod
    def _extract_tool_ids(cls, tools: list[dict]) -> list[int]:
        """
        Extract Tools from Tool ConfigurationID

        Args:
            tools: Tool Configuration List

        Returns:
            ToolsIDVertical
        """
        tool_ids = []
        for tool in tools:
            # Tolerate both raw dicts (linsight config / session_version.tools)
            # and pydantic ToolConfig models (daily config re-validates tools on
            # assignment, so its parent rows come back as models, not dicts).
            if hasattr(tool, "model_dump"):
                tool = tool.model_dump()
            children = tool.get("children")
            if children:
                tool_ids.extend(int(child.get("id")) for child in children if child.get("id"))
        return tool_ids

    @classmethod
    async def download_file(cls, file_info: DownloadFilesSchema) -> tuple[str, bytes]:
        """Download individual files"""

        minio_client = await get_minio_storage()

        object_name = file_info.file_url
        object_name = object_name.replace(f"/{minio_client.bucket}/", "")
        try:
            bytes_io = BytesIO()

            file_byte = await minio_client.get_object(bucket_name=minio_client.bucket, object_name=object_name)
            bytes_io.write(file_byte)

            bytes_io.seek(0)

            return file_info.file_name, bytes_io.getvalue()

        except Exception as e:
            logger.error(f"Download failed {object_name}: {e}")
            return object_name, b""

    @classmethod
    async def batch_download_files(cls, file_info_list: list[DownloadFilesSchema]) -> bytes:
        """
        Batch Download Files

        Args:
            file_info_list: File Information List

        Returns:
            List containing file download information
        """

        # Batch Download Files
        download_tasks = [cls.download_file(file_info) for file_info in file_info_list]

        results = await asyncio.gather(*download_tasks)

        # Filter download failed files
        successful_files = [res for res in results if res[1]]

        if not successful_files:
            raise ValueError("File not downloaded successfully, could not be generatedZIP")

        zip_bytes = util.bytes_to_zip(successful_files)
        return zip_bytes
