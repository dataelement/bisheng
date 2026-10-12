"""Task mode over the Open API (F073).

Every permission decision happens here, at submit time, against the current
permission actor that the F053 pipeline installed (the service account in self
identity, the delegated user when acting on someone's behalf). The linsight
worker does no user-level checks while it runs (design decision 4), so what is
not rejected here is not rejected at all.

The configuration query is built from the same sources and filters as these
checks (``usable_models``, the tool ``use`` filter, the enabled-skill set, the
library ``use`` / space ``visible`` listings), so anything it lists is accepted
at submit (spec AC-05).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from starlette.concurrency import iterate_in_threadpool

from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.cursor import CursorDecodeError, decode_cursor, encode_cursor
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.errcode.knowledge import KnowledgeNotExistError, KnowledgeTypeNotSupportedError
from bisheng.common.errcode.knowledge_space import (
    KnowledgeSpaceInvalidCursorError,
    SpaceNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.common.errcode.open_api import (
    OpenApiContentBlockedError,
    OpenApiModelUnavailableError,
    OpenApiTaskAlreadyFinishedError,
    OpenApiTaskModeForbiddenError,
    OpenApiTaskSkillUnavailableError,
    OpenApiToolUnavailableError,
)
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.common.schemas.api import PageInfiniteCursorData
from bisheng.database.models.role_access import WebMenuResource
from bisheng.database.models.session import MessageSessionDao
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.services.temp_upload_service import TempUploadService
from bisheng.linsight.domain.models.linsight_execute_task import ExecuteTaskStatusEnum, LinsightExecuteTaskDao
from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersion,
    LinsightSessionVersionDao,
    SessionVersionStatusEnum,
)
from bisheng.linsight.domain.services.unattended_run import OPEN_API_CHANNEL
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.schemas.task_mode import (
    OpenTaskAttachmentIssue,
    OpenTaskFailure,
    OpenTaskFile,
    OpenTaskProgress,
    OpenTaskResult,
    OpenTaskSkill,
    OpenTaskStatus,
    OpenTaskSubmitReq,
    OpenTaskSubmitted,
    OpenTaskUnavailableDeliverable,
    OpenTaskView,
)
from bisheng.open_api.domain.schemas.workstation import OpenDailyToolPayload
from bisheng.open_api.domain.services.session_subject_service import session_subject_from_principal

SESSION_NAME_MAX_CHARS = 30
KNOWLEDGE_PAGE_MAX = 100
_SPACE_VISIBLE_MAX_RESULTS = 5_000
_SPACE_CURSOR_CONTEXT = "open_task|knowledge_space"

_STATUS_MAP: dict[SessionVersionStatusEnum, OpenTaskStatus] = {
    SessionVersionStatusEnum.NOT_STARTED: OpenTaskStatus.QUEUED,
    SessionVersionStatusEnum.IN_PROGRESS: OpenTaskStatus.RUNNING,
    SessionVersionStatusEnum.WAITING_FOR_USER_INPUT: OpenTaskStatus.WAITING_INPUT,
    SessionVersionStatusEnum.COMPLETED: OpenTaskStatus.COMPLETED,
    SessionVersionStatusEnum.FAILED: OpenTaskStatus.FAILED,
    SessionVersionStatusEnum.SOP_GENERATION_FAILED: OpenTaskStatus.FAILED,
    SessionVersionStatusEnum.TERMINATED: OpenTaskStatus.TERMINATED,
}
# Finished runs cannot be stopped. v1 lets FAILED through and overwrites it
# with TERMINATED; the Open API answers 409 instead (design decision 13).
_FINISHED = {
    SessionVersionStatusEnum.COMPLETED,
    SessionVersionStatusEnum.FAILED,
    SessionVersionStatusEnum.SOP_GENERATION_FAILED,
    SessionVersionStatusEnum.TERMINATED,
}


def _session_name(text: str) -> str:
    """Conversation name from the task text (no LLM call, design decision 3)."""

    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:SESSION_NAME_MAX_CHARS]
    return "New Chat"


def validate_body(model, payload: dict):
    """Validate a raw JSON body the way FastAPI would for a typed body parameter.

    The chat endpoint takes a raw body so it can dispatch on ``run_mode``; this
    keeps the validation error payload identical to FastAPI's own
    (``loc`` prefixed with ``"body"``, no ``url``), so the daily contract and
    the v2 validation handler see exactly what they saw before.
    """
    from fastapi.exceptions import RequestValidationError
    from pydantic import ValidationError

    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        errors = [{**err, "loc": ("body", *err.get("loc", ()))} for err in exc.errors(include_url=False)]
        raise RequestValidationError(errors, body=payload) from exc


def parse_task_submission(payload: dict) -> OpenTaskSubmitReq:
    """Task-mode body: transport and conversation are rejected with their own codes first."""
    from bisheng.common.errcode.open_api import (
        OpenApiTaskConversationNotAcceptedError,
        OpenApiTaskModeSyncUnsupportedError,
    )

    if payload.get("execution") != "async":
        raise OpenApiTaskModeSyncUnsupportedError()
    if payload.get("conversationId") not in (None, ""):
        raise OpenApiTaskConversationNotAcceptedError()
    return validate_body(OpenTaskSubmitReq, payload)


class OpenTaskModeService:
    # ------------------------------------------------------------------ checks

    @staticmethod
    async def check_task_mode_access(principal: OpenApiPrincipal) -> None:
        """Acting for a user requires that user's task-mode permission.

        Self identity is not checked: a service account never logs into the
        workbench and has no menu permissions (PRD §4.2).
        """
        if principal.mode != "D" or principal.effective_user_id is None:
            return
        try:
            await UserPayload.assert_effective_web_menu_contains(
                principal.effective_user_id, WebMenuResource.LINSIGHT_TASK_MODE.value
            )
        except HTTPException as exc:
            raise OpenApiTaskModeForbiddenError() from exc

    @staticmethod
    async def model_is_usable(model_id) -> bool:
        """Exists, is an LLM, its provider exists, and it is online."""
        from bisheng.llm.domain.const import LLMModelType
        from bisheng.llm.domain.llm.base import BishengBase

        try:
            numeric_id = int(model_id)
        except (TypeError, ValueError):
            return False
        model_info, server_info = await BishengBase.get_model_server_info(numeric_id)
        return bool(
            model_info is not None
            and server_info is not None
            and model_info.model_type == LLMModelType.LLM.value
            and model_info.online
        )

    @classmethod
    async def usable_models(cls, config: dict) -> list[dict]:
        """The workbench models this run may use — the list the config query shows.

        The workbench list alone keeps offline and non-LLM entries, so it is
        filtered with the same test ``check_model`` applies (spec AC-05, AC-06).
        """
        models = list(config.get("models", []))
        usable = await asyncio.gather(*(cls.model_is_usable(item.get("id")) for item in models))
        return [item for item, ok in zip(models, usable, strict=True) if ok]

    @classmethod
    async def check_model(cls, model_id: str, config: dict) -> None:
        allowed = {str(item.get("id")) for item in config.get("models", [])}
        if str(model_id) not in allowed or not await cls.model_is_usable(model_id):
            raise OpenApiModelUnavailableError(model=model_id)

    @staticmethod
    async def enabled_skill_rows() -> list:
        from bisheng.linsight.domain.models.linsight_skill import LinsightSkillDao

        return list(await LinsightSkillDao.list_enabled())

    @classmethod
    async def check_skills(cls, names: list[str] | None) -> None:
        if not names:
            return
        enabled = {row.name for row in await cls.enabled_skill_rows()}
        missing = [name for name in names if name not in enabled]
        if missing:
            raise OpenApiTaskSkillUnavailableError(unavailable=missing)

    @staticmethod
    def check_tools(tools: list[OpenDailyToolPayload] | None, config: dict) -> None:
        available = {
            (int(child.get("id", 0) or 0), str(child.get("tool_key") or ""))
            for group in config.get("tools", [])
            for child in group.get("children", [])
            if isinstance(child, dict)
        }
        for tool in tools or []:
            requested = (int(tool.id or 0), str(tool.tool_key or ""))
            if requested not in available:
                raise OpenApiToolUnavailableError(tool_id=tool.id, tool_key=tool.tool_key)

    @staticmethod
    async def check_knowledge_libraries(login_user: UserPayload, ids: list[int] | None) -> None:
        from bisheng.permission.application.business_authorization import batch_check_business_actions

        if not ids:
            return
        rows = {row.id: row for row in await KnowledgeDao.aget_list_by_ids(list(ids))}
        for knowledge_id in ids:
            row = rows.get(knowledge_id)
            if row is None:
                raise KnowledgeNotExistError(knowledge_id=knowledge_id)
            if row.type != KnowledgeTypeEnum.NORMAL.value:
                raise KnowledgeTypeNotSupportedError(knowledge_id=knowledge_id)
        allowed = await batch_check_business_actions(
            login_user, resource_type="knowledge_library", resource_ids=ids, actions=("use",)
        )
        for knowledge_id in ids:
            if "use" not in allowed.get(str(knowledge_id), frozenset()):
                raise PermissionDeniedError(knowledge_id=knowledge_id)

    @staticmethod
    async def check_knowledge_spaces(login_user: UserPayload, ids: list[int] | None) -> None:
        from bisheng.permission.application.business_authorization import batch_check_business_visible

        if not ids:
            return
        rows = {row.id: row for row in await KnowledgeDao.aget_list_by_ids(list(ids))}
        for space_id in ids:
            row = rows.get(space_id)
            if row is None or row.type != KnowledgeTypeEnum.SPACE.value:
                raise SpaceNotFoundError(knowledge_space_id=space_id)
        visible = await batch_check_business_visible(login_user, resource_type="knowledge_space", resource_ids=ids)
        for space_id in ids:
            if not visible.get(str(space_id)):
                raise SpacePermissionDeniedError(knowledge_space_id=space_id)

    @staticmethod
    def check_content(login_user: UserPayload, *texts: str | None) -> None:
        from bisheng.sensitive_word.domain.services.sensitive_word_policy_service import (
            SensitiveWordPolicyService,
        )
        from bisheng.workstation.domain.services.content_safety import workbench_tenant_id

        tenant_id = workbench_tenant_id(login_user)
        for text in texts:
            if not text:
                continue
            blocked = SensitiveWordPolicyService.evaluate_workbench_user_text(tenant_id, text)
            if blocked:
                logger.warning("open api task-mode content safety hit tenant_id={}", tenant_id)
                raise OpenApiContentBlockedError(auto_reply=blocked.auto_reply or "")

    # ------------------------------------------------------------------ submit

    @classmethod
    async def submit(
        cls, principal: OpenApiPrincipal, req: OpenTaskSubmitReq, login_user: UserPayload
    ) -> OpenTaskSubmitted:
        from bisheng.workstation.domain.services.task_submit_service import submit_task_turn
        from bisheng.workstation.domain.services.workstation_service import WorkStationService

        subject = session_subject_from_principal(principal)
        await cls.check_task_mode_access(principal)
        await TempUploadService.assert_owned_references(req.file_refs(), subject)
        config = await WorkStationService.get_open_api_daily_config(login_user)
        await cls.check_model(req.model, config)
        await cls.check_skills(req.skills)
        cls.check_tools(req.tools, config)
        await cls.check_knowledge_libraries(login_user, req.knowledge_ids)
        await cls.check_knowledge_spaces(login_user, req.knowledge_space_ids)
        # Before anything is written: a blocked submission leaves no conversation.
        cls.check_content(login_user, req.text, req.instructions)

        _session, version = await submit_task_turn(
            req.to_internal(),
            login_user,
            session_subject=subject,
            api_meta={
                "channel": OPEN_API_CHANNEL,
                "instructions": req.instructions,
                "credential_id": principal.credential_id,
                "identity_mode": principal.mode,
            },
            telemetry_source="api",
            session_name=_session_name(req.text),
            strict_enqueue=True,
        )
        return OpenTaskSubmitted(
            task_id=version.id,
            status=OpenTaskStatus.QUEUED,
            queue_position=await cls._queue_position(version.id),
        )

    # ------------------------------------------------------------------ read

    @staticmethod
    async def load_owned(principal: OpenApiPrincipal, task_id: str) -> tuple[LinsightSessionVersion, SessionSubject]:
        """The task if it belongs to this caller, else 404 (never 403: no probing)."""

        version = await LinsightSessionVersionDao.get_by_id(task_id)
        if version is None:
            raise NotFoundError()
        session = await MessageSessionDao.async_get_one(version.session_id)
        subject = session_subject_from_principal(principal)
        if session is None or not subject.matches(session):
            raise NotFoundError()
        return version, subject

    @classmethod
    async def get_view(cls, principal: OpenApiPrincipal, task_id: str) -> OpenTaskView:
        version, _subject = await cls.load_owned(principal, task_id)
        return await cls.build_view(version)

    @classmethod
    async def build_view(cls, version: LinsightSessionVersion) -> OpenTaskView:
        status = _STATUS_MAP.get(version.status, OpenTaskStatus.FAILED)
        output = version.output_result if isinstance(version.output_result, dict) else {}
        view = OpenTaskView(
            task_id=version.id,
            status=status,
            created_at=version.create_time,
            updated_at=version.update_time,
        )
        if status is OpenTaskStatus.QUEUED:
            view.queue_position = await cls._queue_position(version.id)
        elif status is OpenTaskStatus.RUNNING:
            view.progress = await cls._progress(version.id)
        elif status is OpenTaskStatus.COMPLETED:
            view.partial = bool(output.get("partial"))
            view.result = await cls._result(version, output)
        elif status is OpenTaskStatus.FAILED:
            view.failure = OpenTaskFailure(
                category=str(output.get("error_type") or "unknown"),
                message=output.get("error_message"),
            )
        return view

    @staticmethod
    async def _queue_position(task_id: str) -> int | None:
        """1-based position, or None when the queue does not hold it.

        ``LinsightQueue.index`` answers 0 for "already taken / finished /
        missing / a resume item" alike, so 0 is never a position.
        """
        from bisheng.core.cache.redis_manager import get_redis_client
        from bisheng.linsight.worker import LinsightQueue

        try:
            queue = LinsightQueue("queue", namespace="linsight", redis=await get_redis_client())
            index = await queue.index(task_id)
        except Exception:
            logger.exception(f"[OPEN_TASK] queue position lookup failed task_id={task_id}")
            return None
        return index if index and index > 0 else None

    @staticmethod
    async def _progress(task_id: str) -> OpenTaskProgress | None:
        rows = await LinsightExecuteTaskDao.get_by_session_version_id(task_id, is_parent_task=True)
        # The session-level pseudo task (id == svid, "执行准备") is not a todo.
        todos = [row for row in rows if str(row.id) != str(task_id)]
        if not todos:
            return None
        done = sum(1 for row in todos if row.status == ExecuteTaskStatusEnum.SUCCESS)
        return OpenTaskProgress(done=done, total=len(todos))

    @classmethod
    async def _result(cls, version: LinsightSessionVersion, output: dict) -> OpenTaskResult:
        from bisheng.citation.domain.services.citation_handle_service import strip_citation_handles
        from bisheng.citation.domain.services.citation_prompt_helper import strip_citation_markers

        answer = strip_citation_handles(strip_citation_markers(str(output.get("answer") or "")))
        entries = [item for item in output.get("final_files") or [] if isinstance(item, dict)]
        sizes = await asyncio.gather(*(cls._object_size(item.get("file_url")) for item in entries))
        files = [
            OpenTaskFile(
                file_id=str(item.get("file_id") or ""),
                file_name=str(item.get("file_name") or ""),
                file_type=os.path.splitext(str(item.get("file_name") or ""))[1].lstrip(".").lower(),
                size=size,
                primary=index == 0,
            )
            for index, (item, size) in enumerate(zip(entries, sizes, strict=True))
            if item.get("file_id")
        ]
        unavailable = [
            OpenTaskUnavailableDeliverable(file_name=str(name), reason="not_generated")
            for name in output.get("phantom_deliverables") or []
        ] + [
            OpenTaskUnavailableDeliverable(file_name=str(item.get("file_name") or ""), reason="invalid_format")
            for item in output.get("invalid_deliverables") or []
            if isinstance(item, dict)
        ]
        attachments = [
            OpenTaskAttachmentIssue(
                file_name=str(item.get("original_filename") or item.get("file_name") or ""),
                reason=str(item.get("parsing_status") or "failed"),
            )
            for item in version.files or []
            if isinstance(item, dict) and item.get("valid") is False
        ]
        return OpenTaskResult(answer=answer, files=files, unavailable_deliverables=unavailable, attachments=attachments)

    @staticmethod
    async def _object_size(object_name: str | None) -> int | None:
        from bisheng.core.storage.minio.minio_manager import get_minio_storage

        if not object_name:
            return None
        try:
            minio = await get_minio_storage()
            stat = await asyncio.to_thread(minio.minio_client_sync.stat_object, minio.bucket, object_name)
            return int(stat.size)
        except Exception:
            logger.warning(f"[OPEN_TASK] could not stat artifact {object_name!r}")
            return None

    # ------------------------------------------------------------------ download

    @classmethod
    async def download(cls, principal: OpenApiPrincipal, task_id: str, file_id: str) -> StreamingResponse:
        from urllib.parse import quote

        from bisheng.core.storage.minio.minio_manager import get_minio_storage

        version, _subject = await cls.load_owned(principal, task_id)
        output = version.output_result if isinstance(version.output_result, dict) else {}
        entry = next(
            (
                item
                for item in output.get("final_files") or []
                if isinstance(item, dict) and str(item.get("file_id")) == str(file_id)
            ),
            None,
        )
        # Only files in this task's own deliverable list are reachable (the v1
        # download would sign any object key, PRD appendix A item 2).
        if entry is None or not entry.get("file_url"):
            raise NotFoundError()
        minio = await get_minio_storage()
        try:
            response = await asyncio.to_thread(minio.download_object_sync, object_name=entry["file_url"])
        except Exception as exc:
            logger.warning(f"[OPEN_TASK] artifact missing task_id={task_id} file_id={file_id}: {exc}")
            raise NotFoundError() from exc

        def _chunks():
            try:
                yield from response.stream(64 * 1024)
            finally:
                response.close()
                response.release_conn()

        file_name = str(entry.get("file_name") or file_id)
        return StreamingResponse(
            iterate_in_threadpool(_chunks()),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(file_name)}"},
        )

    # ------------------------------------------------------------------ terminate

    @classmethod
    async def terminate(cls, principal: OpenApiPrincipal, task_id: str) -> OpenTaskView:
        from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl

        version, _subject = await cls.load_owned(principal, task_id)
        if version.status in _FINISHED:
            raise OpenApiTaskAlreadyFinishedError(status=_STATUS_MAP[version.status].value)
        await LinsightWorkbenchImpl.terminate(version)
        return await cls.build_view(version)

    # ------------------------------------------------------------------ configuration

    @classmethod
    async def task_config(cls, principal: OpenApiPrincipal, login_user: UserPayload) -> dict:
        from bisheng.llm.domain.services import LLMService
        from bisheng.workstation.domain.services.workstation_service import WorkStationService

        await cls.check_task_mode_access(principal)
        config = await WorkStationService.get_open_api_daily_config(login_user)
        workbench = await LLMService.get_workbench_llm()
        default_model_id = getattr(workbench, "linsight_default_model_id", None)
        models = await cls.usable_models(config)
        allowed_models = {str(item.get("id")) for item in models}
        skills = [
            OpenTaskSkill(name=row.name, display_name=row.display_name or row.name, description=row.description)
            for row in await cls.enabled_skill_rows()
        ]
        return {
            "models": models,
            "default_model_id": default_model_id if str(default_model_id) in allowed_models else None,
            "tools": config.get("tools", []),
            "skills": [skill.model_dump() for skill in skills],
        }

    @classmethod
    async def list_knowledge(
        cls,
        request: Request,
        principal: OpenApiPrincipal,
        login_user: UserPayload,
        *,
        knowledge_type: str,
        name: str | None,
        cursor: str | None,
        page_size: int,
    ) -> PageInfiniteCursorData:
        await cls.check_task_mode_access(principal)
        page_size = max(1, min(int(page_size or 20), KNOWLEDGE_PAGE_MAX))
        if knowledge_type == "library":
            return await cls._list_libraries(request, login_user, name, cursor, page_size)
        if knowledge_type == "space":
            return await cls._list_spaces(login_user, name, cursor, page_size)
        raise KnowledgeTypeNotSupportedError(knowledge_type=knowledge_type)

    @staticmethod
    async def _list_libraries(
        request: Request, login_user: UserPayload, name: str | None, cursor: str | None, page_size: int
    ) -> PageInfiniteCursorData:
        from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService

        page = await KnowledgeService.get_knowledge(
            request,
            login_user,
            KnowledgeTypeEnum.NORMAL,
            name=name,
            cursor=cursor,
            page_size=page_size,
            action="use",  # the same action the submit check requires
        )
        return PageInfiniteCursorData(
            data=[_knowledge_item(row) for row in page.data],
            page_size=page.page_size,
            has_more=page.has_more,
            next_cursor=page.next_cursor,
        )

    @staticmethod
    async def _list_spaces(
        login_user: UserPayload, name: str | None, cursor: str | None, page_size: int
    ) -> PageInfiniteCursorData:
        """Spaces the actor can see — the same ``visible`` the submit check uses.

        Not "created + joined" (``KnowledgeSpaceService.alist_mine_and_joined_cursor``):
        "created" is keyed by ``login_user.user_id``, which in self identity is
        the resource owner, not the service account.
        """
        from bisheng.permission.application.access import get_f048_runtime
        from bisheng.permission.application.identity import resolve_permission_actor

        try:
            decoded = decode_cursor(cursor, expected_key_len=1, expected_context=_SPACE_CURSOR_CONTEXT)
        except CursorDecodeError as exc:
            raise KnowledgeSpaceInvalidCursorError(exception=exc) from exc
        page_num = decoded[0] if decoded else 1
        if not isinstance(page_num, int) or page_num < 1:
            raise KnowledgeSpaceInvalidCursorError()

        actor = await resolve_permission_actor(login_user)
        runtime = await get_f048_runtime()
        visible = await runtime.list_visible_objects(
            actor, resource_type="knowledge_space", max_results=_SPACE_VISIBLE_MAX_RESULTS
        )
        ids = [int(value) for value in visible.object_ids]
        rows = (
            [row for row in await KnowledgeDao.aget_list_by_ids(ids) if row.type == KnowledgeTypeEnum.SPACE.value]
            if ids
            else []
        )
        if name:
            keyword = name.strip().lower()
            rows = [row for row in rows if row.name and keyword in row.name.lower()]
        rows.sort(key=lambda row: (row.update_time or row.create_time or datetime.min, row.id), reverse=True)

        start = (page_num - 1) * page_size
        window = rows[start : start + page_size + 1]
        has_more = len(window) > page_size
        return PageInfiniteCursorData(
            data=[_knowledge_item(row) for row in window[:page_size]],
            page_size=page_size,
            has_more=has_more,
            next_cursor=encode_cursor((page_num + 1,), context=_SPACE_CURSOR_CONTEXT) if has_more else None,
        )


def _knowledge_item(row) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "description": getattr(row, "description", None),
        "update_time": getattr(row, "update_time", None),
    }


__all__ = ["OpenTaskModeService", "parse_task_submission", "validate_body"]
