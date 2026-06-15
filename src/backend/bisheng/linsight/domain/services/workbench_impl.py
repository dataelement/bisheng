import asyncio
import json
import os
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from io import BytesIO
from typing import Any
from urllib.parse import unquote

from e2b.sandbox.filesystem.filesystem import WriteEntry
from fastapi import UploadFile
from langchain_core.tools import BaseTool
from loguru import logger

from bisheng.api.services.workstation import WorkStationService
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum, BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.linsight import LinsightBishengLLMError, LinsightGenerateSopError, LinsightToolInitError
from bisheng.common.schemas.telemetry.event_data_schema import NewMessageSessionEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.cache.utils import CACHE_DIR, save_file_to_folder
from bisheng.core.logger import trace_id_var
from bisheng.core.prompts.manager import get_prompt_manager
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.database.models.flow import FlowType
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import KnowledgeRead, KnowledgeTypeEnum
from bisheng.linsight.domain import utils as linsight_execute_utils
from bisheng.linsight.domain.models.linsight_execute_task import LinsightExecuteTaskDao
from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersion,
    LinsightSessionVersionDao,
    SessionVersionStatusEnum,
)
from bisheng.linsight.domain.models.linsight_sop import LinsightSOPRecord
from bisheng.linsight.domain.schemas.linsight_schema import (
    DownloadFilesSchema,
    LinsightQuestionSubmitSchema,
    SubmitFileSchema,
)
from bisheng.linsight.domain.services.sop_manage import SOPManageService
from bisheng.llm.domain.llm import BishengLLM
from bisheng.llm.domain.services import LLMService
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.tool.domain.services.executor import ToolExecutor
from bisheng.tool.domain.services.tool import ToolServices
from bisheng.utils import util
from bisheng.utils.util import async_calculate_md5
from bisheng_langchain.linsight.const import ExecConfig


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
    COLLECTION_NAME_PREFIX = "col_linsight_file_"
    FILE_INFO_REDIS_KEY_PREFIX = "linsight_file:"
    CACHE_EXPIRATION_HOURS = 24

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

        processed_files = await cls._process_submitted_files(files, linsight_session_version.session_id)

        if linsight_session_version.files:
            linsight_session_version.files.extend(processed_files)
        else:
            linsight_session_version.files = processed_files

        await LinsightSessionVersionDao.insert_one(linsight_session_version)

        return processed_files

    @classmethod
    async def submit_user_question(
        cls, submit_obj: LinsightQuestionSubmitSchema, login_user: UserPayload
    ) -> tuple[MessageSession, LinsightSessionVersion]:
        """
        Submit user issue and create session

        Args:
            submit_obj: Submitted Question Objects
            login_user: Logged in user information

        Returns:
            tuple: (Message Session Model, Inspiration Conversation Version Model)

        Raises:
            LinsightError: When creating a session fails
        """
        try:
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

            # Process files (if present) — after chat_id is finalized
            processed_files = await cls._process_submitted_files(submit_obj.files, chat_id)

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

            # Create Ideas Conversation Version
            linsight_session_version = LinsightSessionVersion(
                session_id=chat_id,
                user_id=login_user.user_id,
                question=submit_obj.question,
                tools=submit_obj.tools,
                org_knowledge_enabled=submit_obj.org_knowledge_enabled,
                personal_knowledge_enabled=submit_obj.personal_knowledge_enabled,
                files=processed_files,
                model=submit_obj.model,
            )
            linsight_session_version = await LinsightSessionVersionDao.insert_one(linsight_session_version)

            # F035 Track J: land the user question in the unified conversation
            # stream so the round reads as one Q→A pair regardless of task mode.
            # (The bot answer turn is written at completion in task_exec.)
            await linsight_execute_utils.persist_task_user_turn(
                chat_id=chat_id, user_id=login_user.user_id, question=submit_obj.question
            )

            return message_session, linsight_session_version

        except Exception as e:
            logger.error(f"Failed to submit user question: {e!s}")
            raise cls.LinsightError(f"Failed to submit user question: {e!s}")

    @classmethod
    async def _get_redis(cls):
        """Return the redis client (indirection so tests can patch it)."""
        return await get_redis_client()

    @classmethod
    async def _process_submitted_files(cls, files: list[SubmitFileSchema] | None, chat_id: str) -> list | None:
        """Process submitted files (F035: offload-first ingestion).

        For each submitted file:
          1. Resolve parsed-markdown metadata. Prefer the formal-bucket product
             already produced in this session (idempotent re-entry, TC-5); fall
             back to the temp metadata in Redis (``linsight_file:{file_id}``).
          2. Copy temp -> formal bucket only on first processing (skipped when a
             formal product already exists).
          3. Write the parsed markdown into the session **workspace**
             (``workspace/{chat_id}/uploads/<name>/index.md``) so deepagents file
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

        Returns:
            List of processed file metadata dicts (one per submitted file).
        """
        if not files:
            return None

        for file in files:
            if file.parsing_status != "completed":
                raise cls.LinsightError(f"file {file.file_name} status is error: {file.parsing_status}")

        file_ids = [file.file_id for file in files]
        redis_keys = [f"{cls.FILE_INFO_REDIS_KEY_PREFIX}{file_id}" for file_id in file_ids]
        redis_client = await cls._get_redis()
        temp_infos = await redis_client.amget(redis_keys)

        minio_client = await get_minio_storage()

        processed_files: list[dict] = []
        for submit_file, temp_info in zip(files, temp_infos):
            entry = await cls._ingest_one_file(submit_file, temp_info, chat_id, minio_client)
            processed_files.append(entry)

        return processed_files

    @classmethod
    async def _ingest_one_file(
        cls, submit_file: SubmitFileSchema, temp_info: dict | None, chat_id: str, minio_client
    ) -> dict:
        """Ingest a single submitted file into the session workspace.

        Idempotent on re-entry: a formal-bucket product produced earlier in this
        session is reused; the temp->formal copy is performed only once.
        """
        # Idempotency: reuse a formal-bucket product produced earlier this session.
        formal_object = cls._formal_markdown_object(submit_file.file_id, chat_id)
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
        entry["parsing_status"] = "completed"
        entry["valid"] = True
        entry["markdown_file_path"] = formal_object
        entry["markdown_filename"] = f"{cls._sanitize_name(entry['original_filename'])}.md"

        # Write parsed markdown into the workspace (uploads/<name>/index.md).
        await cls._write_attachment_to_workspace(entry, chat_id, minio_client)
        return entry

    @staticmethod
    def _formal_markdown_object(file_id: str, chat_id: str) -> str:
        """Stable formal-bucket object key for a file's parsed markdown.

        Stable per (chat_id, file_id) so a resubmission of the same file_id maps
        to the same object and ``object_exists`` makes the copy idempotent.
        """
        return f"linsight/{chat_id}/{file_id}.md"

    @staticmethod
    def _sanitize_name(original_filename: str) -> str:
        """Normalize an original filename to a safe workspace ``<name>``.

        Lowercased, illegal characters normalized to '-', traversal-safe.
        (Same naming discipline as Skill names, design §9.3.2.)
        """
        import re

        stem = original_filename.rsplit(".", 1)[0] if "." in original_filename else original_filename
        stem = stem.strip().lower()
        stem = re.sub(r"[^a-z0-9._-]+", "-", stem).strip("-._")
        return stem or "file"

    @classmethod
    async def _write_attachment_to_workspace(cls, entry: dict, chat_id: str, minio_client) -> None:
        """Write parsed markdown into the session workspace and set pointer metadata.

        Workspace layout (design §9.3.2):
            workspace/{chat_id}/uploads/<name>/index.md
        Sets ``workspace_path`` / ``line_count`` / ``image_count`` on ``entry``
        for the zero-body pointer block (``prepare_file_list``).
        """
        from bisheng.linsight.domain.services.workspace_backend import WORKSPACE_PREFIX

        name = cls._sanitize_name(entry["original_filename"])
        rel_path = f"uploads/{name}/index.md"
        object_key = f"{WORKSPACE_PREFIX}/{chat_id}/{rel_path}"

        # Read the parsed markdown (formal bucket) and write it into the workspace.
        markdown_bytes = await minio_client.get_object(
            bucket_name=minio_client.bucket, object_name=entry["markdown_file_path"]
        )
        if markdown_bytes is None:
            markdown_bytes = b""
        await minio_client.put_object(
            bucket_name=minio_client.bucket,
            object_name=object_key,
            file=markdown_bytes,
            content_type="text/markdown",
        )

        text = markdown_bytes.decode("utf-8", errors="replace")
        entry["workspace_path"] = f"/{rel_path}"
        entry["line_count"] = entry.get("line_count") or (text.count("\n") + 1 if text else 0)
        entry["image_count"] = entry.get("image_count", 0)

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

            if not task_title.content:
                raise ValueError("Failed to generate task title, please check the model configuration or input")

            # Update session title
            await cls._update_session_title(chat_id, task_title.content)

            return {"task_title": task_title.content, "chat_id": chat_id, "error_message": None}

        except Exception as e:
            logger.error(f"Failed to generate task title: {e!s}")
            return {"task_title": "New Chat", "chat_id": chat_id, "error_message": str(e)}

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
    async def modify_sop(cls, linsight_session_version_id: str, sop_content: str) -> dict:
        """
        Modify Inspiration Conversation Version ofSOPContents

        Args:
            linsight_session_version_id: Session VersionID
            sop_content: SOPContents

        Returns:
            Operating result
        """
        try:
            await LinsightSessionVersionDao.modify_sop_content(
                linsight_session_version_id=linsight_session_version_id, sop_content=sop_content
            )
            return {"success": True, "message": "modify sop content successfully"}
        except Exception as e:
            logger.error(f"ChangeSOPContent failed: {e!s}")
            raise cls.LinsightError(str(e))

    @classmethod
    async def generate_sop(
        cls,
        linsight_session_version_id: str,
        previous_session_version_id: str | None = None,
        feedback_content: str | None = None,
        reexecute: bool = False,
        login_user: UserPayload | None = None,
        knowledge_list: list[KnowledgeRead] = None,
        example_sop: str | None = None,
    ) -> AsyncGenerator[dict, None]:
        """
        BuatSOPContents

        Args:
            linsight_session_version_id: Current Session VersionID
            previous_session_version_id: Previous Session VersionID
            feedback_content: Content of feedback
            reexecute: Whether to re-execute
            login_user: Logged in user information
            knowledge_list: Knowledge Base Columns
            example_sop: Ref.sop, incoming when doing the same modelsopContents

        Yields:
            Date GeneratedSOPContent Events
        """
        error_message = None
        try:
            # Get workbench configuration and session version
            session_version = await cls._get_session_version(linsight_session_version_id)

            if login_user.user_id != session_version.user_id:
                yield UnAuthorizedError().to_sse_event_instance()
                return
            try:
                # BuatLLMand tools
                llm, workbench_conf = await cls._get_llm(session_version.user_id)
            except Exception as e:
                logger.error(f"BuatSOPContent failed: session_version_id={linsight_session_version_id}, error={e!s}")
                raise cls.BishengLLMError(str(e))
            tools = await cls._prepare_tools(session_version, llm)

            # Preparation History Summary
            history_summary = await cls._prepare_history_summary(reexecute, previous_session_version_id)

            # Create proxy and generateSOP
            agent = await cls._create_linsight_agent(session_version, llm, tools, workbench_conf)

            if previous_session_version_id:
                session_version = await LinsightSessionVersionDao.get_by_id(previous_session_version_id)

            content = ""
            async for res in cls._generate_sop_content(
                agent,
                session_version,
                feedback_content,
                history_summary,
                knowledge_list,
                example_sop=example_sop,
                login_user=login_user,
            ):
                if isinstance(res, cls.SearchSOPError):
                    yield res.error_class.to_sse_event(event="search_sop_error")
                    continue

                content += res.content
                yield {"event": "generate_sop_content", "data": res.model_dump_json()}

            # Update session version status and sop content
            await LinsightSessionVersionDao.modify_sop_content(
                linsight_session_version_id=linsight_session_version_id, sop_content=content
            )

            logger.info(f"BuatSOPContent Success: session_version_id={linsight_session_version_id}")

        except cls.ToolsInitializationError as e:
            logger.exception(
                f"Failed to initialize the Inspiration Workbench tool: session_version_id={linsight_session_version_id}, error={e!s}"
            )
            error_message = LinsightToolInitError(exception=e)
        except cls.BishengLLMError as e:
            logger.exception(f"Bisheng LLMError-free: session_version_id={linsight_session_version_id}, error={e!s}")
            error_message = LinsightBishengLLMError(exception=e)
        except Exception as e:
            logger.exception(f"BuatSOPContent failed: session_version_id={linsight_session_version_id}, error={e!s}")
            error_message = LinsightGenerateSopError(exception=e)

        finally:
            if error_message:
                session_version = await LinsightSessionVersionDao.get_by_id(linsight_session_version_id)
                if session_version:
                    session_version.sop = f"{error_message.Msg}: {error_message.exception!s}"
                    session_version.status = SessionVersionStatusEnum.SOP_GENERATION_FAILED
                    await LinsightSessionVersionDao.insert_one(session_version)
                yield error_message.to_sse_event_instance()

    @classmethod
    async def _get_session_version(cls, session_version_id: str) -> LinsightSessionVersion:
        """Get session version"""
        session_version = await LinsightSessionVersionDao.get_by_id(session_version_id)
        if not session_version:
            raise cls.LinsightError("Inspiration session version does not exist")
        return session_version

    @classmethod
    async def _prepare_tools(cls, session_version: LinsightSessionVersion, llm: BishengLLM) -> list[BaseTool]:
        """Preparation Tools List"""
        try:
            tools = await cls.init_linsight_config_tools(session_version, llm)

            root_path = os.path.join(CACHE_DIR, "linsight", session_version.id)
            os.makedirs(root_path, exist_ok=True)

            linsight_tools = await ToolServices.init_linsight_tools(root_path=root_path)
            tools.extend(linsight_tools)

            return tools
        except Exception as e:
            raise cls.ToolsInitializationError(str(e))

    @classmethod
    async def prepare_file_list(cls, session_version: LinsightSessionVersion) -> list[str]:
        """Prepare the zero-body ``<uploaded_files>`` pointer block (design §9.3.3).

        Each valid attachment becomes a pointer item (path + name + lines +
        images) — **no file body or preview** is injected, preserving the
        offload-first contract (the model reads bodies on demand via
        ``read_file``). Invalid attachments (expired metadata) are skipped here;
        the frontend surfaces them via the ``valid=False`` flag.

        Returns:
            A single-element list holding the ``<uploaded_files>`` block, or an
            empty list when there are no valid attachments. (A list is returned
            for parity with ``parse_file_list_str`` which joins on newlines.)
        """
        if not session_version.files:
            return []

        items: list[str] = []
        for file in session_version.files:
            if file.get("valid") is False:
                continue
            path = file.get("workspace_path") or f"/uploads/{file.get('file_id')}/index.md"
            items.append(
                "- path: {path}\n  name: {name}\n  lines: {lines}\n  images: {images}".format(
                    path=path,
                    name=file.get("original_filename", ""),
                    lines=file.get("line_count", 0),
                    images=file.get("image_count", 0),
                )
            )

        if not items:
            return []

        block = "<uploaded_files>\n" + "\n".join(items) + "\n</uploaded_files>"
        return [block]

    @classmethod
    async def prepare_knowledge_list(cls, knowledge_list: list[KnowledgeRead]) -> list[str]:
        res = []
        if not knowledge_list:
            return res
        # Check if there is a personal knowledge base
        template_str = (
            """@{name}Stored information for:{{'The knowledge base is stored in a semantic repositoryid':'{id}'}}@"""
        )
        for one in knowledge_list:
            if one.type == KnowledgeTypeEnum.PRIVATE.value:
                res.append(template_str.format(name="Personal Knowledge Base", id=one.id))
            else:
                knowledge_str = template_str.format(name=one.name, id=one.id)
                if one.description:
                    knowledge_str += f"，{one.name}is described as{one.description}"
                res.append(knowledge_str)
        return res

    @classmethod
    async def _prepare_history_summary(cls, reexecute: bool, previous_session_version_id: str) -> list[str]:
        """Preparation History Summary"""
        history_summary = []

        if reexecute and previous_session_version_id:
            execute_tasks = await LinsightExecuteTaskDao.get_by_session_version_id(previous_session_version_id)

            for task in execute_tasks:
                if task.result:
                    answer = task.result.get("answer", "")
                    if answer:
                        history_summary.append(answer)

        return history_summary

    @classmethod
    async def _create_linsight_agent(
        cls, session_version: LinsightSessionVersion, llm: BishengLLM, tools: list[BaseTool], workbench_conf
    ):
        """BuatLinsightAgent"""
        from bisheng_langchain.linsight.agent import LinsightAgent

        root_path = os.path.join(CACHE_DIR, "linsight", session_version.id[:8])
        linsight_conf = settings.get_linsight_conf()
        exec_config = ExecConfig(**linsight_conf.model_dump(), debug_id=session_version.id)
        return LinsightAgent(
            file_dir=root_path,
            query=session_version.question,
            llm=llm,
            tools=tools,
            exec_config=exec_config,
        )

    @classmethod
    async def _generate_sop_content(
        cls,
        agent,
        session_version: LinsightSessionVersion,
        feedback_content: str | None,
        history_summary: list[str],
        knowledge_list: list[KnowledgeRead] = None,
        example_sop: str = None,
        login_user: UserPayload | None = None,
    ) -> AsyncGenerator:
        """BuatSOPContents"""
        file_list = await cls.prepare_file_list(session_version)
        knowledge_list = await cls.prepare_knowledge_list(knowledge_list)
        if example_sop:
            async for res in agent.generate_sop(sop=example_sop, file_list=file_list, knowledge_list=knowledge_list):
                yield res
        elif feedback_content is None:
            # RetrieveSOPTemplates
            sop_template, search_sop_error = await SOPManageService.search_sop(
                invoke_user_id=login_user.user_id, query=session_version.question, k=3
            )

            if search_sop_error:
                search_sop_error: BaseErrorCode
                logger.error(f"RetrieveSOPTemplate failed: {search_sop_error.Msg}")
                yield cls.SearchSOPError(error_class=search_sop_error)

            sop_template = "\n\n".join([f"Examples:\n\n{sop.page_content}" for sop in sop_template if sop.page_content])

            async for res in agent.generate_sop(sop=sop_template, file_list=file_list, knowledge_list=knowledge_list):
                yield res
        else:
            sop_template = session_version.sop if session_version.sop else ""

            async for res in agent.feedback_sop(
                sop=sop_template,
                feedback=feedback_content,
                history_summary=history_summary if history_summary else None,
                file_list=file_list,
                knowledge_list=knowledge_list,
            ):
                yield res

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
        # Generate file information
        file_id = uuid.uuid4().hex[:8]  # Buat8Bit Unique FileID
        # url <g id="Bold">Code</g> decode The file name
        original_filename = unquote(file.filename)
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
            # Get workbench configuration
            workbench_conf = await cls._get_workbench_config()
            collection_name = f"{cls.COLLECTION_NAME_PREFIX}{workbench_conf.embedding_model.id}"

            # Asynchronous execution of file parsing
            parse_result = await cls._parse_file(
                invoke_user_id, file_id, file_path, original_filename, collection_name, workbench_conf
            )

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
        collection_name: str,
        workbench_conf,
    ) -> dict:
        """
        Synchronize parsed files

        Args:
            file_id: Doc.ID
            file_path: FilePath
            original_filename: Original Filename
            collection_name: Set Name
            workbench_conf: Workbench configuration

        Returns:
            Parsing results
        """
        # Read file contents
        try:
            from bisheng.api.v1.schemas import FileProcessBase
            from bisheng.knowledge.rag.temp_file_pipeline import TempFilePipeline

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

            # Process vector storage
            await cls._process_vector_storage(invoke_user_id, texts, file_id, collection_name, workbench_conf)

            return {
                "file_id": file_id,
                "original_filename": original_filename,
                "parsing_status": "completed",
                "parse_type": parse_type,
                "markdown_filename": markdown_filename,
                "markdown_file_path": markdown_filename,
                "markdown_file_md5": markdown_md5,
                "embedding_model_id": workbench_conf.embedding_model.id,
                "collection_name": collection_name,
            }
        except Exception as e:
            logger.error(f"File parsing failed: file_id={file_id}, error={e!s}")
            return {
                "file_id": file_id,
                "original_filename": original_filename,
                "parsing_status": "failed",
                "error_message": str(e),
            }

    @classmethod
    async def _process_vector_storage(
        cls, invoke_user_id: int, texts: list[str], file_id: str, collection_name: str, workbench_conf
    ) -> None:
        """Process vector storage"""
        # Buatembeddings
        embeddings = await LLMService.get_bisheng_linsight_embedding(
            model_id=workbench_conf.embedding_model.id, invoke_user_id=invoke_user_id
        )

        # Create Vector Store
        vector_client = KnowledgeRag.init_milvus_vectorstore(collection_name=collection_name, embeddings=embeddings)
        es_client = KnowledgeRag.init_es_vectorstore(collection_name)

        # Adding Text to Vector Storage
        metadatas = [{"file_id": file_id} for _ in texts]
        await vector_client.aadd_texts(texts, metadatas=metadatas)
        await es_client.aadd_texts(texts, metadatas=metadatas)

    @classmethod
    async def _cache_parse_result(cls, file_id: str, parse_result: dict) -> None:
        """Cache Result"""
        redis_client = await get_redis_client()
        key = f"{cls.FILE_INFO_REDIS_KEY_PREFIX}{file_id}"
        await redis_client.aset(key=key, value=parse_result, expiration=60 * 60 * cls.CACHE_EXPIRATION_HOURS)

    @classmethod
    async def _init_bisheng_code_tool(cls, config_tool_ids: list[int], file_dir: str, user_id: int) -> list[BaseTool]:
        """
        Code interpreter tool for special handling initialization Bi Lift
        """
        tools = []
        bisheng_code_tool = await GptsToolsDao.aget_tool_by_tool_key(tool_key="bisheng_code_interpreter")
        if not bisheng_code_tool or bisheng_code_tool.id not in config_tool_ids:
            return tools
        # Individual initialization code interpreter tool
        config_tool_ids.remove(bisheng_code_tool.id)
        code_config = json.loads(bisheng_code_tool.extra) if bisheng_code_tool.extra else {}
        if "config" not in code_config:
            code_config["config"] = {}
        if "local" not in code_config["config"]:
            code_config["config"]["local"] = {}
        code_config["config"]["local"]["local_sync_path"] = file_dir
        if "e2b" not in code_config["config"]:
            code_config["config"]["e2b"] = {}
        code_config["config"]["e2b"]["local_sync_path"] = file_dir
        # Default60Validity period of minutes
        code_config["config"]["e2b"]["timeout"] = 3600
        code_config["config"]["e2b"]["keep_sandbox"] = True
        file_list = []
        for root, dirs, files in os.walk(file_dir):
            for file in files:
                file_path = os.path.join(root, file)
                file_list.append(WriteEntry(data=file_path, path=file_path.replace(file_dir, ".")))
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
        tool_ids = cls._extract_tool_ids(session_version.tools)

        # Tools to get workbench configurationsID
        linsight_config = await WorkStationService.get_linsight_config()
        config_tool_ids = cls._extract_tool_ids(linsight_config.tools or [])

        # todo Better tool initialization scheme
        if need_upload and file_dir:
            try:
                bisheng_code_tool = await cls._init_bisheng_code_tool(
                    config_tool_ids, file_dir, user_id=session_version.user_id
                )
                tools.extend(bisheng_code_tool)
            except Exception as e:
                logger.error(
                    f"Failed to initialize BiSheng code interpreter tool: session_version_id={session_version.id}, error={e!s}"
                )

        # Filter Effective ToolsID
        valid_tool_ids = [tid for tid in tool_ids if tid in config_tool_ids]

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
            if tool.get("children"):
                tool_ids.extend(int(child.get("id")) for child in tool["children"] if child.get("id"))
        return tool_ids

    @classmethod
    async def feedback_regenerate_sop_task(cls, session_version_model: LinsightSessionVersion, feedback: str) -> None:
        """
        Regenerate from feedbackSOPTask

        Args:
            session_version_model: Inspiration Conversation Version Model
            feedback: Content of feedback
        """
        try:
            file_list = await cls.prepare_file_list(session_version_model)

            # BuatLLMand tools
            llm, workbench_conf = await cls._get_llm(session_version_model.user_id)
            tools = await cls._prepare_tools(session_version_model, llm)

            # Get a summary of your history
            history_summary = await cls._get_history_summary(session_version_model.id)

            # Create proxy and generateSOP
            agent = await cls._create_linsight_agent(session_version_model, llm, tools, workbench_conf)

            sop_content = ""
            sop_template = session_version_model.sop or ""

            async for res in agent.feedback_sop(
                sop=sop_template,
                feedback=feedback,
                history_summary=history_summary if history_summary else None,
                file_list=file_list,
            ):
                sop_content += res.content

            # sopWrite it down on the record sheet, thissopThere is no need to associate sessions because there is no need to update scores
            await SOPManageService.add_sop_record(
                LinsightSOPRecord(
                    name=session_version_model.title,
                    description=None,
                    user_id=session_version_model.user_id,
                    content=sop_content,
                )
            )
        except cls.ToolsInitializationError as e:
            logger.exception(
                f"Failed to initialize the Inspiration Workbench tool: session_version_id={session_version_model.id}, error={e!s}"
            )

        except Exception as e:
            logger.exception(
                f"Feedback regenerationSOPMisi Gagal: session_version_id={session_version_model.id}, error={e!s}"
            )

    @classmethod
    async def _get_history_summary(cls, session_version_id: str) -> list[str]:
        """Get a summary of your history"""
        history_summary = []
        execute_tasks = await LinsightExecuteTaskDao.get_by_session_version_id(session_version_id)

        for task in execute_tasks:
            if task.result:
                answer = task.result.get("answer", "")
                if answer:
                    history_summary.append(answer)

        return history_summary

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
