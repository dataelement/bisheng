"""F004 T057 (design 决策 12): attachments of a ``direct`` run are read on demand.

Three parts:

``start_upload_parsing``     called by the daily upload endpoint. With the unified
    runtime on for the tenant, parsing starts at upload. The state uses deep
    research's key (``linsight_file:{file_id}``) and shape, so
    ``/linsight/workbench/file-parsing-status`` answers for these files too.
``WorkspaceAttachmentSource`` puts one attachment into the conversation workspace
    (``workspace/{conversation_id}/uploads/``) with deep research's ingestion
    (``LinsightWorkbenchImpl._ingest_one_file`` / ``_ingest_daily_file``).
``AttachmentIntake``         what one execution does with its attachments: it does
    not wait for parsing before the first model request, lists every attachment
    with its path, inlines small parsed files, and makes reads of ``uploads/``
    wait for files that are still being parsed.

Images (design §7 item 18): a model that takes images gets the picture in its
input, and the original is ALSO written to ``uploads/<name>`` in the background,
so a later run can ``read_file`` it or open it in the code interpreter. The
first model request does not wait for that write; its input names the path.

State lives in Redis and object storage only (C8): the node that parses at
upload and the node that runs need not be the same.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from loguru import logger

from bisheng.core.cache.utils import async_file_download

# Defaults of ``linsight.direct_attachment_inline_chars`` / ``..._inline_total_chars``.
# NOT measured on real daily attachments. Basis: the per-file value is half of the
# 8000 characters a tool result keeps in an event; the total is the legacy cap of
# inlined attachment text (``WorkstationConfig.maxTokens`` default, 15000 characters),
# so a first request never carries more attachment text than it does today.
DEFAULT_INLINE_FILE_CHARS = 4000
DEFAULT_INLINE_TOTAL_CHARS = 15000
# A parse reported as "running" for longer than this is treated as dead (the node
# that ran it went away); the run parses the file itself. 600 s is the ETL ceiling.
PARSE_WAIT_SECONDS = 600.0
PARSE_POLL_SECONDS = 0.5
_STATE_TTL_SECONDS = 24 * 3600

# Upload-time parses and ingestions that outlive their run; referenced so the
# event loop does not drop them.
_PARSE_TASKS: set[asyncio.Task] = set()
_BACKGROUND: set[asyncio.Task] = set()


def _state_key(file_id: str) -> str:
    from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl

    return f"{LinsightWorkbenchImpl.FILE_INFO_REDIS_KEY_PREFIX}{file_id}"


async def _set_state(file_id: str, value: dict) -> None:
    from bisheng.core.cache.redis_manager import get_redis_client

    await (await get_redis_client()).aset(key=_state_key(file_id), value=value, expiration=_STATE_TTL_SECONDS)


async def _get_state(file_id: str) -> dict | None:
    from bisheng.core.cache.redis_manager import get_redis_client

    value = await (await get_redis_client()).aget(_state_key(file_id))
    return value if isinstance(value, dict) else None


async def _unified_runtime_enabled(tenant_id: int | None) -> bool:
    from bisheng.workstation.domain.services.workstation_service import is_unified_runtime_enabled

    return await is_unified_runtime_enabled(tenant_id)


def file_name_of(item: dict) -> str:
    return str(item.get("file_name") or item.get("filename") or item.get("name") or item.get("filepath") or "")


def file_id_of(item: dict) -> str:
    """The upload's ``file_id``; an item without one gets a stable id from its path."""
    file_id = str(item.get("file_id") or "")
    if file_id:
        return file_id
    return hashlib.md5(str(item.get("filepath") or "").split("?")[0].encode()).hexdigest()[:16]


# ------------------------------------------------------------------ upload


async def start_upload_parsing(payload: dict, *, user_id: int, tenant_id: int | None) -> bool:
    """Start parsing an uploaded daily attachment. False (and no effect) when the switch is off.

    Never raises: a failure here must not fail the upload. The run then finds no
    state and parses the file itself.
    """
    try:
        if not await _unified_runtime_enabled(tenant_id):
            return False
        file_id, filepath, name = str(payload.get("file_id") or ""), payload.get("filepath"), file_name_of(payload)
        if not file_id or not filepath:
            return False
        await _set_state(
            file_id,
            {
                "file_id": file_id,
                "original_filename": name,
                "parsing_status": "running",
                "file_url": filepath,
                "started_at": time.time(),
            },
        )
    except Exception:
        logger.exception("could not start parsing the uploaded attachment {!r}", payload.get("filename"))
        return False
    task = asyncio.create_task(parse_uploaded(file_id, filepath, name, user_id), name=f"attachment-parse:{file_id}")
    _PARSE_TASKS.add(task)
    task.add_done_callback(_PARSE_TASKS.discard)
    return True


async def parse_uploaded(file_id: str, filepath: str, name: str, user_id: int) -> dict:
    """Parse one uploaded file into the temp bucket and record the result (deep research's parser)."""
    from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl

    try:
        local_path, _ = await async_file_download(filepath)
        result = await LinsightWorkbenchImpl._parse_file(user_id, file_id, local_path, name)
    except Exception as exc:
        logger.exception("parsing the uploaded attachment {!r} (file_id={}) failed", name, file_id)
        result = {"file_id": file_id, "original_filename": name, "parsing_status": "failed", "error_message": str(exc)}
    result = {**result, "file_url": filepath}
    try:
        await _set_state(file_id, result)
    except Exception:
        # The state stays "running"; a run treats it as dead after PARSE_WAIT_SECONDS.
        logger.exception("could not record the parse result of attachment {!r} (file_id={})", name, file_id)
    return result


# ------------------------------------------------------------------- names


@dataclass
class WorkspaceNames:
    """Where one attachment will be in the workspace, known before it is parsed.

    ``path``  what ``read_file`` takes (``/uploads/x.md``); None when there is no text view.
    ``raw``   the original, relative to the code interpreter's working directory; None when not kept.
    ``seed``  the names earlier attachments of the same message took. Passing a copy
              as ``used_names`` to the ingestion makes it pick exactly ``path`` / ``raw``,
              whatever order the files are processed in.
    """

    path: str | None = None
    raw: str | None = None
    seed: frozenset[str] = field(default_factory=frozenset)


def plan_workspace_names(files: list[dict], originals: frozenset[int] | set[int] = frozenset()) -> list[WorkspaceNames]:
    """The names ``LinsightWorkbenchImpl._write_attachment_to_workspace`` will give, in message order.

    ``originals``: indexes of the files stored as themselves whatever their type
    (the images a visual model gets directly, see ``WorkspaceAttachmentSource.store_image``).

    A prediction: a file whose parse fails, or a workbook above the carry ceiling,
    ends up elsewhere. The listing tells the model to ``ls`` when a path is missing.
    """
    from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl as impl

    used: set[str] = set()
    plans: list[WorkspaceNames] = []
    for index, item in enumerate(files):
        seed = frozenset(used)
        safe = impl._safe_basename(file_name_of(item))
        ext = os.path.splitext(safe)[1].lower().lstrip(".")
        route = "passthrough" if index in originals else impl._ingest_route(safe)
        if route == "passthrough":
            name = impl._dedupe_workspace_name(safe, used)
            plans.append(WorkspaceNames(f"/uploads/{name}", f"uploads/{name}", seed))
        elif route == "original":
            plans.append(WorkspaceNames(None, f"uploads/{impl._dedupe_workspace_name(safe, used)}", seed))
        elif route == "parse":
            stem = safe.rsplit(".", 1)[0] if "." in safe else safe
            markdown = impl._dedupe_workspace_name(f"{stem}.md", used)
            raw = impl._dedupe_workspace_name(safe, used) if ext in impl._RAW_KEEP_EXTS else None
            plans.append(WorkspaceNames(f"/uploads/{markdown}", f"uploads/{raw}" if raw else None, seed))
        else:
            plans.append(WorkspaceNames(None, None, seed))
    return plans


def touches_uploads(path: str | None) -> bool:
    """Whether a file operation on ``path`` can see ``uploads/`` (the root does)."""
    rel = (path or "").strip().lstrip("/")
    return rel in ("", "uploads") or rel.startswith("uploads/")


# ------------------------------------------------------------------ source


class WorkspaceAttachmentSource:
    """Production source: the upload-parse state in Redis, the workspace in object storage."""

    def __init__(
        self,
        *,
        object_store: Callable[[], Awaitable[Any]] | None = None,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        clock: Callable[[], float] = time.time,
        inline_chars: int | None = None,
        inline_total_chars: int | None = None,
    ):
        self._object_store = object_store or self._default_object_store
        self._sleep = sleep
        self._clock = clock
        conf = None
        if inline_chars is None or inline_total_chars is None:
            conf = self._conf()
        self.inline_chars = (
            inline_chars
            if inline_chars is not None
            else int(getattr(conf, "direct_attachment_inline_chars", DEFAULT_INLINE_FILE_CHARS))
        )
        self.inline_total_chars = (
            inline_total_chars
            if inline_total_chars is not None
            else int(getattr(conf, "direct_attachment_inline_total_chars", DEFAULT_INLINE_TOTAL_CHARS))
        )

    @staticmethod
    def _conf() -> Any:
        from bisheng.common.services.config_service import settings

        return settings.get_linsight_conf()

    @staticmethod
    async def _default_object_store() -> Any:
        from bisheng.core.storage.minio.minio_manager import get_minio_storage

        return await get_minio_storage()

    def _running(self, state: dict | None) -> bool:
        if not state or state.get("parsing_status") != "running":
            return False
        return self._clock() - float(state.get("started_at") or 0.0) < PARSE_WAIT_SECONDS

    async def ready(self, ctx: Any, file: dict) -> bool:
        """The upload-time parse has finished: bringing the file in is a copy, not a parse."""
        state = await _get_state(file_id_of(file))
        return bool(state and state.get("parsing_status") == "completed" and state.get("markdown_file_path"))

    async def visual(self, ctx: Any) -> bool:
        """Whether the run's model takes images (the workbench model list says so)."""
        from bisheng.workstation.domain.services.workstation_service import WorkStationService

        ws_config = await WorkStationService.aget_config()
        models = getattr(ws_config, "models", None) or []
        model_info = next((m for m in models if str(getattr(m, "id", "")) == str(ctx.model_id)), None)
        if model_info is None:
            logger.warning(
                "direct run={}: model {} not in the workbench config; images are parsed as documents",
                ctx.run_id,
                ctx.model_id,
            )
            return False
        return bool(getattr(model_info, "visual", False))

    async def image_data_url(self, ctx: Any, file: dict) -> str:
        from bisheng.workstation.domain.services.chat_helpers import read_image_as_data_url

        local_path, name = await async_file_download(file["filepath"])
        return await read_image_as_data_url(filepath=local_path, filename=name)

    async def store_image(self, ctx: Any, file: dict, used_names: set[str]) -> dict:
        """Write the original of an image to ``workspace/{conversation_id}/uploads/<name>``.

        For an image a visual model gets directly: no parse. Same naming and the
        same objects as a passthrough attachment (``_finalize_passthrough``): the
        formal object ``linsight/{conversation_id}/{file_id}.<ext>`` and the
        workspace file, so ``read_file`` returns the picture and the code
        interpreter opens ``uploads/<name>``. Returns deep research's entry.
        """
        from bisheng.linsight.domain.schemas.linsight_schema import SubmitFileSchema
        from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl

        local_path, downloaded_name = await async_file_download(file["filepath"])
        raw = await LinsightWorkbenchImpl._read_local_bytes(local_path)
        if raw is None:
            raise OSError(f"image bytes unavailable after download: {file_name_of(file)!r}")
        name = file_name_of(file) or downloaded_name
        submit = SubmitFileSchema(
            file_id=file_id_of(file), file_name=name, parsing_status="completed", file_url=file.get("filepath")
        )
        entry = await LinsightWorkbenchImpl._finalize_passthrough(
            submit, name, ctx.conversation_id, await self._object_store(), raw, used_names
        )
        # ``_finalize_passthrough`` counts text lines; an image has none.
        entry["line_count"] = 0
        return entry

    async def ingest(self, ctx: Any, file: dict, used_names: set[str]) -> dict:
        """Put one attachment into ``workspace/{conversation_id}/uploads/``; return deep research's entry.

        Waits for an upload-time parse that is still running. A file with no
        usable parse result is parsed here (deep research's daily-file ingestion,
        which keeps the original when parsing fails).
        """
        from bisheng.linsight.domain.schemas.linsight_schema import SubmitFileSchema
        from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl

        file_id = file_id_of(file)
        state = await _get_state(file_id)
        while self._running(state):
            await self._sleep(PARSE_POLL_SECONDS)
            state = await _get_state(file_id)
        submit = SubmitFileSchema(
            file_id=file_id, file_name=file_name_of(file), parsing_status="completed", file_url=file.get("filepath")
        )
        minio = await self._object_store()
        if state and state.get("parsing_status") == "completed" and state.get("markdown_file_path"):
            temp_info = {k: v for k, v in state.items() if k not in ("file_url", "started_at")}
            return await LinsightWorkbenchImpl._ingest_one_file(
                submit, temp_info, ctx.conversation_id, minio, used_names
            )
        if state:
            logger.info(
                "direct run={}: attachment {!r} has no usable upload parse (status={}); parsing it now",
                ctx.run_id,
                submit.file_name,
                state.get("parsing_status"),
            )
        return await LinsightWorkbenchImpl._ingest_daily_file(
            submit, ctx.conversation_id, minio, ctx.user_id, used_names
        )

    async def text(self, ctx: Any, entry: dict) -> str | None:
        """The text view of an ingested attachment, or None when it is too long to inline or not text."""
        from bisheng.linsight.domain.services.workspace_backend import _decode_workspace_text, workspace_prefix_for

        rel = str(entry.get("workspace_path") or "").lstrip("/")
        # Every line has at least one character: more lines than the limit cannot fit.
        if not rel or int(entry.get("line_count") or 0) > self.inline_chars:
            return None
        minio = await self._object_store()
        data = await minio.get_object(
            bucket_name=minio.bucket, object_name=f"{workspace_prefix_for(ctx.conversation_id)}/{rel}"
        )
        return _decode_workspace_text(data or b"", rel)


# ------------------------------------------------------------------ intake


@dataclass
class AttachmentView:
    """What the first model request gets: the listing, the inlined text, the images."""

    listing: str = ""
    file_context: str = ""
    images: list = field(default_factory=list)


def _has_text_view(entry: dict) -> bool:
    return (
        entry.get("valid") is not False
        and bool(entry.get("workspace_path"))
        and entry.get("ingest_mode") != "spreadsheet_original"
    )


def render_image_listing(
    stored: list[tuple[str, WorkspaceNames]], failed: list[str], *, has_code_interpreter: bool
) -> str:
    """The workspace paths of the images a visual model got in its input.

    ``stored``: (name, planned names) of the images written or being written to
    ``uploads/``. ``failed``: names whose write already failed.
    """
    parts: list[str] = []
    if stored:
        note = "以下图片已随本条消息直接提供，同时保存在工作区，之后的对话可用 read_file 读取下面的 path"
        if has_code_interpreter:
            note += "，或在 bisheng_code_interpreter 中按 raw 的相对路径打开"
        note += '；path 读不到时用 ls("/uploads") 查看实际文件名。'
        lines = ["<uploaded_images>", note]
        lines.extend(f"- path: {plan.path}\n  name: {name}\n  raw: {plan.raw}" for name, plan in stored)
        lines.append("</uploaded_images>")
        parts.append("\n".join(lines))
    if failed:
        parts.append("以下图片未能保存到工作区（之后的对话不能用 read_file 读取）：" + "、".join(failed))
    return "\n".join(parts)


async def render_listing(
    entries: list[dict], pending: list[tuple[str, WorkspaceNames]], *, has_code_interpreter: bool
) -> str:
    """The attachment index of the model input: deep research's pointer block plus the files still being parsed."""
    from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl

    parts: list[str] = []
    if entries:
        parts.extend(
            await LinsightWorkbenchImpl.prepare_file_list(
                SimpleNamespace(files=entries), has_code_interpreter=has_code_interpreter
            )
        )
        failed = [e.get("original_filename", "") for e in entries if e.get("valid") is False]
        if failed:
            parts.append("以下附件未能解析，无法读取其内容，请如实告诉用户：" + "、".join(failed))
    if pending:
        lines = [
            "<uploaded_files_pending>",
            "以下附件正在解析，解析完成后出现在工作区。需要其内容时直接 read_file 下面的 path，"
            '工具会等到解析完成再返回；path 读不到时用 ls("/uploads") 查看实际文件名。',
        ]
        for name, plan in pending:
            if plan.path:
                item = f"- path: {plan.path}\n  name: {name}"
                if plan.raw and plan.raw != plan.path.lstrip("/"):
                    item += f"\n  raw: {plan.raw}"
            elif plan.raw:
                item = f"- name: {name}\n  raw: {plan.raw}\n  note: 没有文本视图（不可 read_file）"
                if has_code_interpreter:
                    item += "，用 bisheng_code_interpreter 按 raw 的相对路径读取"
            else:
                item = f"- name: {name}\n  note: 该格式可能无法解析"
            lines.append(item)
        lines.append("</uploaded_files_pending>")
        parts.append("\n".join(lines))
    return "\n".join(parts)


class AttachmentIntake:
    """The attachments of one execution (never kept on the runner: C8).

    ``source``      see ``WorkspaceAttachmentSource`` (tests pass a fake).
    ``emit_frame``  ``await emit_frame(status, extra)`` writes one frame of the
                    "reading attachments" ``tool_call`` (AC-51). The frame opens
                    at ``start`` and closes when every file is in the workspace,
                    so it is open whenever something waits for parsing.
    """

    def __init__(
        self,
        ctx: Any,
        files: list[dict],
        source: Any,
        emit_frame: Callable[[str, dict], Awaitable[None]],
        *,
        has_code_interpreter: bool = False,
    ):
        self.ctx = ctx
        self.files = list(files)
        self.source = source
        self._emit_frame = emit_frame
        self._has_code = has_code_interpreter
        self.plans = plan_workspace_names(self.files)
        self._tasks: dict[int, asyncio.Task] = {}
        self._image_tasks: dict[int, asyncio.Task] = {}
        # index -> the background write of a directly-given image to ``uploads/``.
        # Not part of the progress frame and never awaited by ``first_view``.
        self._image_store_tasks: dict[int, asyncio.Task] = {}
        self._ready: list[int] = []
        self._frame_open = False
        self._frame_closing: asyncio.Task | None = None
        self._closer: asyncio.Task | None = None
        # Set by the runner when the graph starts: from then on parsing continues
        # past the end of the run, so later runs find the file (AC-26).
        self.keep_after_run = False

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Open the progress frame and start bringing every file in. Does not wait for parsing."""
        from bisheng.workstation.domain.services.constants import VISUAL_MODEL_FILE_TYPES

        self._frame_open = True
        await self._emit_frame("start", {})
        image_indexes = [
            i for i, f in enumerate(self.files) if file_name_of(f).rsplit(".", 1)[-1].lower() in VISUAL_MODEL_FILE_TYPES
        ]
        inline_images = bool(image_indexes) and await self.source.visual(self.ctx)
        if inline_images:
            # These images are stored under their own name, not as a parsed ``.md``.
            self.plans = plan_workspace_names(self.files, frozenset(image_indexes))
        ready = await asyncio.gather(*(self.source.ready(self.ctx, f) for f in self.files), return_exceptions=True)
        for index, file in enumerate(self.files):
            if inline_images and index in image_indexes:
                # A model that takes images gets the picture itself, as before.
                self._image_tasks[index] = asyncio.create_task(self.source.image_data_url(self.ctx, file))
                # Also into the workspace, in the background (design §7 item 18).
                self._image_store_tasks[index] = asyncio.create_task(self._store_image(index, file))
                continue
            if ready[index] is True:
                self._ready.append(index)
            elif isinstance(ready[index], BaseException):
                logger.opt(exception=ready[index]).warning(
                    "direct run={}: could not read the parse state of {!r}", self.ctx.run_id, file_name_of(file)
                )
            self._tasks[index] = asyncio.create_task(self._ingest(index, file))
        self._closer = asyncio.create_task(self._close_when_done())

    async def _ingest(self, index: int, file: dict) -> dict:
        """One file into the workspace. A failure degrades this file, never the run."""
        try:
            return await self.source.ingest(self.ctx, file, set(self.plans[index].seed))
        except Exception as exc:
            logger.exception(
                "direct run={} conversation={}: attachment {!r} could not be read",
                self.ctx.run_id,
                self.ctx.conversation_id,
                file_name_of(file),
            )
            return {
                "file_id": file_id_of(file),
                "original_filename": file_name_of(file),
                "parsing_status": "failed",
                "valid": False,
                "error_message": str(exc) or type(exc).__name__,
            }

    async def _store_image(self, index: int, file: dict) -> dict:
        """The original of one directly-given image into ``uploads/``. A failure costs
        only the workspace copy: the model already has the picture."""
        try:
            return await self.source.store_image(self.ctx, file, set(self.plans[index].seed))
        except Exception as exc:
            logger.exception(
                "direct run={} conversation={}: image {!r} could not be written to the workspace uploads/; "
                "later runs cannot read it as a file",
                self.ctx.run_id,
                self.ctx.conversation_id,
                file_name_of(file),
            )
            return {
                "file_id": file_id_of(file),
                "original_filename": file_name_of(file),
                "parsing_status": "failed",
                "valid": False,
                "error_message": str(exc) or type(exc).__name__,
            }

    async def _close_when_done(self) -> None:
        tasks = [*self._tasks.values(), *self._image_tasks.values()]
        if tasks:
            await asyncio.wait(tasks)
        await self._finish_frame()

    async def _finish_frame(self, still_parsing: list[str] | None = None) -> None:
        """Write the end frame once; a second caller waits for the first to finish writing."""
        if self._frame_closing is not None:
            await asyncio.shield(self._frame_closing)
            return
        if not self._frame_open:
            return
        extra: dict[str, Any] = {}
        failed = [
            file_name_of(self.files[i])
            for i, task in self._tasks.items()
            if task.done() and not task.cancelled() and task.result().get("valid") is False
        ]
        failed += [
            file_name_of(self.files[i])
            for i, task in self._image_tasks.items()
            if task.done() and not task.cancelled() and task.exception() is not None
        ]
        if failed:
            extra["failed"] = failed
        if still_parsing:
            extra["still_parsing"] = still_parsing
        self._frame_closing = asyncio.create_task(self._emit_frame("end", extra))
        await asyncio.shield(self._frame_closing)

    @property
    def pending(self) -> bool:
        return any(not task.done() for task in (*self._tasks.values(), *self._image_store_tasks.values()))

    async def wait(self) -> None:
        """Wait until every file is in the workspace; the progress frame closes before this returns."""
        tasks = [task for task in (*self._tasks.values(), *self._image_store_tasks.values()) if not task.done()]
        if tasks:
            logger.info(
                "direct run={} conversation={}: waiting for {} attachment(s) still being parsed",
                self.ctx.run_id,
                self.ctx.conversation_id,
                len(tasks),
            )
            await asyncio.wait(tasks)
        await self._finish_frame()

    async def close(self) -> None:
        """End of the execution: close the frame; unfinished parsing continues or is cancelled."""
        unfinished = {i: t for i, t in {**self._tasks, **self._image_tasks}.items() if not t.done()}
        names = [file_name_of(self.files[i]) for i in unfinished]
        if self._closer is not None and not self._closer.done() and self._frame_closing is None:
            self._closer.cancel()
        try:
            await self._finish_frame(still_parsing=names if self.keep_after_run else None)
        finally:
            for index, task in unfinished.items():
                if self.keep_after_run and index in self._tasks:
                    _BACKGROUND.add(task)
                    task.add_done_callback(_BACKGROUND.discard)
                else:
                    task.cancel()
            for task in self._image_store_tasks.values():
                if task.done():
                    continue
                if self.keep_after_run:
                    # The write goes on after the run, so later runs find the image.
                    _BACKGROUND.add(task)
                    task.add_done_callback(_BACKGROUND.discard)
                else:
                    task.cancel()

    # -- model input -------------------------------------------------------

    async def first_view(self) -> AttachmentView:
        """The attachment part of the first model request.

        Waits only for files whose upload-time parse had finished (a copy) and
        for the images a visual model gets directly.
        """
        waited = [self._tasks[i] for i in self._ready] + list(self._image_tasks.values())
        if waited:
            await asyncio.wait(waited)
        images: list[str] = []
        for index, task in self._image_tasks.items():
            if task.exception() is not None:
                logger.opt(exception=task.exception()).error(
                    "direct run={}: image attachment {!r} could not be loaded",
                    self.ctx.run_id,
                    file_name_of(self.files[index]),
                )
                continue
            images.append(task.result())
        entries: list[dict] = []
        pending: list[tuple[str, WorkspaceNames]] = []
        for index, task in self._tasks.items():
            if task.done() and not task.cancelled():
                entries.append(task.result())
            else:
                pending.append((file_name_of(self.files[index]), self.plans[index]))
        listing = await render_listing(entries, pending, has_code_interpreter=self._has_code)
        failed_images = [file_name_of(self.files[i]) for i, t in self._image_tasks.items() if t.exception() is not None]
        if failed_images:
            listing = "\n".join(
                filter(None, [listing, "以下图片未能读取，请如实告诉用户：" + "、".join(failed_images)])
            )
        listing = "\n".join(filter(None, [listing, self._image_listing()]))
        if not any(not task.done() for task in self._tasks.values()):
            await self._finish_frame()
        return AttachmentView(listing=listing, file_context=await self._inline(entries), images=images)

    def _image_listing(self) -> str:
        """Where the directly-given images are (or will be) in the workspace. Does not wait."""
        stored: list[tuple[str, WorkspaceNames]] = []
        failed: list[str] = []
        for index, task in self._image_store_tasks.items():
            name = file_name_of(self.files[index])
            if task.done() and not task.cancelled() and task.result().get("valid") is False:
                failed.append(name)
            else:
                stored.append((name, self.plans[index]))
        return render_image_listing(stored, failed, has_code_interpreter=self._has_code)

    async def _inline(self, entries: list[dict]) -> str:
        """Text of the small parsed files, within the per-file and the total limit."""
        limit = int(getattr(self.source, "inline_chars", DEFAULT_INLINE_FILE_CHARS))
        budget = int(getattr(self.source, "inline_total_chars", DEFAULT_INLINE_TOTAL_CHARS))
        blocks: list[str] = []
        for entry in entries:
            if not _has_text_view(entry) or budget <= 0:
                continue
            try:
                text = await self.source.text(self.ctx, entry)
            except Exception:
                # The file is listed with its path; the model can still read it.
                logger.exception(
                    "direct run={}: could not load {!r} for inlining", self.ctx.run_id, entry.get("original_filename")
                )
                continue
            if not text or len(text) > limit or len(text) > budget:
                continue
            budget -= len(text)
            blocks.append(
                f"[文件 {entry.get('original_filename', '')}，路径 {entry['workspace_path']}，全文如下]\n{text}"
            )
        return "\n\n".join(blocks)

    # -- waiting reads -----------------------------------------------------

    def guard(self, backend: Any) -> None:
        """Make the backend's reads of ``uploads/`` wait for files that are still being parsed.

        The async methods of this one backend object are wrapped (the graph calls
        the async ones). Other paths are not delayed.
        """
        for name, position in (("aread", 0), ("als", 0), ("aglob", 1), ("agrep", 1)):
            original = getattr(backend, name, None)
            if original is not None:
                setattr(backend, name, self._waiting(original, position))

    def _waiting(self, original: Callable[..., Awaitable[Any]], position: int) -> Callable[..., Awaitable[Any]]:
        async def call(*args: Any, **kwargs: Any) -> Any:
            if self.pending:
                path = args[position] if len(args) > position else kwargs.get("path", kwargs.get("file_path"))
                if touches_uploads(path):
                    await self.wait()
            return await original(*args, **kwargs)

        return call
