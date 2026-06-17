import asyncio
import json
import os
import uuid
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
from bisheng.common.schemas.telemetry.event_data_schema import NewMessageSessionEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.cache.utils import save_file_to_folder
from bisheng.core.logger import trace_id_var
from bisheng.core.prompts.manager import get_prompt_manager
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

            # F035 fix: workspace attachments MUST be keyed by the session_version
            # id (svid), because the execution agent's WorkspaceBackend reads from
            # ``workspace/{svid}/``. In the unified model chat_id != svid, so
            # writing under chat_id left the uploaded file unreadable by the agent
            # (read_file -> MinIO NoSuchKey -> whole task failed). Generate the
            # svid up-front and use it both for ingestion and the version row id.
            svid = uuid.uuid4().hex
            # Process files (if present) — after chat_id is finalized
            processed_files = await cls._process_submitted_files(submit_obj.files, svid, login_user.user_id)

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
    async def _process_submitted_files(
        cls, files: list[SubmitFileSchema] | None, chat_id: str, user_id: int = 0
    ) -> list | None:
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

        # Daily-bucket files (unified-resource) are parsed on-the-fly; only the
        # linsight-pipeline files need a Redis temp_info lookup.
        linsight_files = [f for f in files if not f.file_url]
        redis_keys = [f"{cls.FILE_INFO_REDIS_KEY_PREFIX}{f.file_id}" for f in linsight_files]
        redis_client = await cls._get_redis()
        temp_list = await redis_client.amget(redis_keys) if redis_keys else []
        temp_by_id = {f.file_id: t for f, t in zip(linsight_files, temp_list)}

        minio_client = await get_minio_storage()

        processed_files: list[dict] = []
        for submit_file in files:
            if submit_file.file_url:
                entry = await cls._ingest_daily_file(submit_file, chat_id, minio_client, user_id)
            else:
                entry = await cls._ingest_one_file(
                    submit_file, temp_by_id.get(submit_file.file_id), chat_id, minio_client
                )
            processed_files.append(entry)

        return processed_files

    @classmethod
    async def _ingest_daily_file(cls, submit_file: SubmitFileSchema, chat_id: str, minio_client, user_id: int) -> dict:
        """Ingest a DAILY-bucket file into the linsight workspace (unified-resource).

        The daily upload only stores the raw file (no parse). We reuse the same
        parser the daily chat uses (``TempFilePipeline``): download the raw file,
        extract its text/markdown, write that to the formal bucket, then drop it
        into the workspace as ``uploads/<name>/index.md`` so the offload-first
        file tools (read_file) + ``prepare_file_list`` pointer block see it like
        any linsight-uploaded attachment.
        """
        from bisheng.api.v1.schemas import FileProcessBase
        from bisheng.core.cache.utils import async_file_download
        from bisheng.knowledge.rag.temp_file_pipeline import TempFilePipeline

        try:
            local_path, dl_name = await async_file_download(submit_file.file_url)
            file_name = submit_file.file_name or dl_name
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
        except Exception as e:
            logger.warning(f"daily file ingest failed ({submit_file.file_name}): {e}")
            return {
                "file_id": submit_file.file_id,
                "original_filename": submit_file.file_name,
                "parsing_status": "expired",
                "valid": False,
                "error_message": "file parse failed, please re-upload",
            }

        formal_object = cls._formal_markdown_object(submit_file.file_id, chat_id)
        await minio_client.put_object(
            bucket_name=minio_client.bucket, object_name=formal_object, file=markdown.encode("utf-8")
        )

        entry: dict = {
            "file_id": submit_file.file_id,
            "original_filename": submit_file.file_name,
            "parsing_status": "completed",
            "valid": True,
            "markdown_file_path": formal_object,
            "markdown_filename": f"{cls._sanitize_name(submit_file.file_name)}.md",
        }
        await cls._write_attachment_to_workspace(entry, chat_id, minio_client)
        return entry

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

            return {
                "file_id": file_id,
                "original_filename": original_filename,
                "parsing_status": "completed",
                "parse_type": parse_type,
                "markdown_filename": markdown_filename,
                "markdown_file_path": markdown_filename,
                "markdown_file_md5": markdown_md5,
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

        # Code-interpreter whitelist source. Unified-resource direction
        # (2026-06-16): task mode reuses the DAILY chat config tool selection,
        # not the legacy per-app linsight config. get_daily_chat_config falls
        # back to defaults (never None in practice), but guard defensively so a
        # missing config degrades to an empty whitelist instead of crashing the
        # task with 'NoneType' object has no attribute 'tools'.
        daily_config = await WorkStationService.get_daily_chat_config()
        config_tool_ids = cls._extract_tool_ids(daily_config.tools or []) if daily_config else []

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

        # Unified-resource direction (2026-06-16): task mode reuses the daily
        # tool selection directly. Every selected tool id (a real GptsTools id
        # the user already has access to) binds. config_tool_ids (from the daily
        # chat config) is used only by the code-interpreter branch above.
        valid_tool_ids = list(dict.fromkeys(tool_ids))  # de-dup, preserve order

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
