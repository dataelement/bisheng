import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import HTTPException, Request
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from loguru import logger

from bisheng.api.services.workstation import WorkStationService
from bisheng.api.v1.schema.chat_schema import ChatMessageHistoryResponse
from bisheng.api.v1.schemas import ChatResponse, KnowledgeSpaceConfig
from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum, BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.errcode.knowledge import (
    KnowledgeDepartmentFileUnavailableError,
    KnowledgeDepartmentFileViewApprovalRequiredError,
)
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.common.schemas.telemetry.event_data_schema import PortalQaEventData
from bisheng.common.stream_errors import StreamRetryEvent, StreamStageError, retry_async_stream
from bisheng.common.telemetry.portal_event_service import (
    PORTAL_BFF_TELEMETRY_SOURCE_HEADER,
    PortalTelemetryEventService,
    is_portal_bff_proxy_source,
)
from bisheng.common.utils.title_generator import generate_conversation_title_async
from bisheng.core.prompts.manager import get_prompt_manager
from bisheng.database.constants import MessageCategory
from bisheng.database.models.flow import FlowType
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.database.models.tag import TagDao
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFileDao,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileAccessStatus,
)
from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService
from bisheng.knowledge.rag.version_filter import build_primary_only_filter
from bisheng.llm.domain import LLMService
from bisheng.llm.domain.utils import extract_reasoning_content
from bisheng.tool.domain.langchain.knowledge import KnowledgeRetrieverTool
from bisheng.telemetry.domain.mid_table.realtime_qa_question import (
    RealtimeQaQuestionFact,
)
from bisheng.utils import generate_uuid


class KnowledgeSpaceChatService:
    """Service class for handling Knowledge Space AI Chat operations"""

    def __init__(self, request: Request, login_user: UserPayload):
        self.request = request
        self.login_user = login_user
        self.department_file_view_access_service = None
        self.doc_repo = None
        self.version_repo = None

    def _permission_service(self):
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

        if not hasattr(self, "_knowledge_space_permission_service"):
            self._knowledge_space_permission_service = KnowledgeSpaceService(self.request, self.login_user)
        return self._knowledge_space_permission_service

    async def _require_space_view_permission(self, space_id: int):
        svc = self._permission_service()
        await svc._require_read_permission(space_id)
        await svc._require_permission_id("knowledge_space", space_id, "view_space")

    async def _require_folder_view_permission(self, space_id: int, folder_id: int):
        svc = self._permission_service()
        folder = await svc._require_folder_relation(space_id, folder_id, "can_read")
        await svc._require_permission_id("folder", folder_id, "view_folder", space_id=space_id)
        return folder

    async def _require_file_view_permission(self, space_id: int, file_id: int):
        svc = self._permission_service()
        file_record = await svc._require_file_relation(file_id, "can_read", space_id=space_id)
        await svc._require_permission_id("knowledge_file", file_id, "view_file", space_id=space_id)
        return file_record

    async def _require_portal_file_view_permission(
        self,
        space_id: int,
        file_id: int,
    ):
        file_record = await KnowledgeFileDao.query_by_id(file_id)
        if (
            file_record is None
            or int(file_record.knowledge_id) != int(space_id)
            or int(file_record.file_type) != FileType.FILE.value
            or int(file_record.status) != KnowledgeFileStatus.SUCCESS.value
        ):
            raise NotFoundError(msg="Knowledge file not found for chat")
        access_service = self.department_file_view_access_service
        if access_service is None:
            raise RuntimeError("DepartmentFileViewAccessService 未注入")
        decision = await access_service.evaluate_file(
            login_user=self.login_user,
            file=file_record,
        )
        if decision.status == DepartmentFileAccessStatus.ALLOWED:
            return file_record
        if decision.status == DepartmentFileAccessStatus.APPROVAL_REQUIRED:
            raise KnowledgeDepartmentFileViewApprovalRequiredError()
        if decision.status == DepartmentFileAccessStatus.UNAVAILABLE:
            raise KnowledgeDepartmentFileUnavailableError()
        return await self._require_file_view_permission(space_id, file_id)

    @classmethod
    def generate_flow_id_for_file(cls, knowledge_id: int, file_id: int) -> str:
        """Generate a unique flow_id representation for a single file chat"""
        return f"space_{knowledge_id}_file_{file_id}"

    @classmethod
    def generate_flow_id_for_folder(cls, knowledge_id: int, folder_id: int = 0) -> str:
        """Generate a unique flow_id representation for a folder chat"""
        return f"space_{knowledge_id}_folder_{folder_id}"

    async def chat_single_file(
        self, knowledge_id: int, file_id: int, query: str, model_id: int
    ) -> AsyncIterator[ChatResponse | StreamRetryEvent]:
        """Single file RAG query"""
        file_record = await self._require_file_view_permission(knowledge_id, file_id)
        async for item in self._chat_single_file_authorized(
            knowledge_id=knowledge_id,
            file_id=file_id,
            query=query,
            model_id=model_id,
            file_record=file_record,
        ):
            yield item

    async def chat_single_file_for_portal(
        self,
        knowledge_id: int,
        file_id: int,
        query: str,
        model_id: int,
    ) -> AsyncIterator[ChatResponse | StreamRetryEvent]:
        file_record = await self._require_portal_file_view_permission(
            knowledge_id,
            file_id,
        )
        async for item in self._chat_single_file_authorized(
            knowledge_id=knowledge_id,
            file_id=file_id,
            query=query,
            model_id=model_id,
            file_record=file_record,
        ):
            yield item

    async def _chat_single_file_authorized(
        self,
        *,
        knowledge_id: int,
        file_id: int,
        query: str,
        model_id: int,
        file_record,
    ) -> AsyncIterator[ChatResponse | StreamRetryEvent]:
        space = await KnowledgeDao.aquery_by_id(file_record.knowledge_id)
        if not space:
            raise NotFoundError(msg="Knowledge space not found for chat")

        flow_id = self.generate_flow_id_for_file(knowledge_id, file_id)

        session = await MessageSessionDao.afilter_session(
            flow_ids=[flow_id],
            flow_type=[FlowType.KNOLEDGE_SPACE.value],
            user_ids=[self.login_user.user_id],
            include_delete=False,
        )
        if not session:
            session = await MessageSessionDao.async_insert_one(
                MessageSession(
                    chat_id=generate_uuid(),
                    flow_id=flow_id,
                    flow_name=file_record.file_name,
                    flow_type=FlowType.KNOLEDGE_SPACE.value,
                    user_id=self.login_user.user_id,
                )
            )
        else:
            session = session[0]

        milvus_vector = await KnowledgeRag.init_knowledge_milvus_vectorstore(self.login_user.user_id, knowledge=space)
        vector_retriever = milvus_vector.as_retriever(
            search_kwargs={"k": 100, "param": {"ef": 110}, "expr": f"document_id == {file_id}"}
        )
        es_vector = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=space)
        es_retriever = es_vector.as_retriever(search_kwargs={"filter": [{"term": {"metadata.document_id": file_id}}]})
        has_answer = False
        question_id = generate_uuid()
        async for one in self.space_rag(
            session,
            vector_retriever,
            es_retriever,
            query,
            model_id,
            None,
            knowledge_id=knowledge_id,
            preauthorized_file_ids={int(file_id)},
        ):
            if not isinstance(one, StreamRetryEvent):
                has_answer = True
            yield one
        if has_answer:
            await self._log_portal_document_qa_success(
                knowledge_id=knowledge_id,
                file_id=file_id,
                question_id=question_id,
                conversation_id=session.chat_id,
            )

    def _is_portal_bff_proxy_request(self) -> bool:
        return is_portal_bff_proxy_source(self.request.headers.get(PORTAL_BFF_TELEMETRY_SOURCE_HEADER))

    async def _log_portal_document_qa_success(
        self,
        *,
        knowledge_id: int,
        file_id: int,
        question_id: str,
        conversation_id: str,
    ) -> None:
        if self._is_portal_bff_proxy_request():
            return
        try:
            PortalTelemetryEventService.log_event_sync(
                user_id=self.login_user.user_id,
                event_type=BaseTelemetryTypeEnum.PORTAL_QA,
                event_data=PortalQaEventData(
                    source_app="bisheng_my_knowledge",
                    scene="my_knowledge_document_qa",
                    entry_point="my_knowledge_document_qa",
                    resource_type="document",
                    space_id=knowledge_id,
                    file_id=file_id,
                    question_id=question_id,
                    conversation_id=conversation_id,
                    status="success",
                ),
            )
        except Exception:
            logger.exception("Failed to log portal document QA telemetry.")
        try:
            await RealtimeQaQuestionFact.record_success(
                tenant_id=self.login_user.tenant_id,
                user_id=self.login_user.user_id,
                user_name=self.login_user.user_name,
                question_id=question_id,
                qa_type="document",
                scene="my_knowledge_document_qa",
                source_app="bisheng_my_knowledge",
                space_id=knowledge_id,
                file_id=file_id,
                conversation_id=conversation_id,
            )
        except Exception:
            logger.exception("Failed to project portal document QA telemetry.")

    async def space_rag(
        self,
        session,
        vector_retriever,
        es_retriever,
        query: str,
        model_id: int,
        tags: Any = None,
        *,
        knowledge_id: int | None = None,
        preauthorized_file_ids: set[int] | None = None,
    ) -> AsyncIterator[ChatResponse | StreamRetryEvent]:
        try:
            llm, space_conf = await self.get_space_llm_config(model_id=model_id)
        except Exception as error:
            raise StreamStageError(error, stage="config") from error

        try:
            finally_docs = await self._retrieve_visible_documents(
                query=query,
                vector_retriever=vector_retriever,
                es_retriever=es_retriever,
                max_content=space_conf.max_chunk_size,
                sort_by_source_and_index=True,
                knowledge_id=knowledge_id,
                preauthorized_file_ids=preauthorized_file_ids,
            )
        except Exception as error:
            raise StreamStageError(error, stage="retrieval") from error
        logger.debug(f"retrieved_finally_docs: {len(finally_docs)}")
        file_content = ""
        for one in finally_docs:
            file_content += one.page_content + "\n"

        prompt_service = await get_prompt_manager()

        if space_conf.system_prompt:
            inputs = [
                SystemMessage(content=space_conf.system_prompt.format(cur_date=datetime.now().strftime("%Y-%m-%d"))),
                HumanMessage(
                    content=space_conf.user_prompt.format(retrieved_file_content=file_content, question=query)
                ),
            ]
        else:
            prompt_obj = prompt_service.render_prompt(
                namespace="knowledge_space",
                prompt_name="rag_prompt",
                cur_date=datetime.now().strftime("%Y-%m-%d"),
                retrieved_file_content=file_content,
                question=query,
            )
            inputs = [SystemMessage(content=prompt_obj.prompt.system), HumanMessage(content=prompt_obj.prompt.user)]
        answer = ""
        reasoning_content = ""
        history = await self.get_history(chat_id=session.chat_id, limit=4)
        if history:
            history.append(inputs[1])
            history.insert(0, inputs[0])
            inputs = history

        logger.info(
            "space_rag llm inputs | chat_id={} model_id={} retrieved_chunks={} | messages={}",
            session.chat_id,
            model_id,
            len(finally_docs),
            [{"role": m.type, "content": m.content} for m in inputs],
        )

        def is_visible_model_chunk(chunk) -> bool:
            return bool(getattr(chunk, "content", "") or extract_reasoning_content(chunk))

        try:
            async for one in retry_async_stream(
                lambda: llm.astream(inputs),
                stage="model",
                is_output=is_visible_model_chunk,
            ):
                if isinstance(one, StreamRetryEvent):
                    yield one
                    continue
                chunk_reasoning_content = extract_reasoning_content(one)
                yield ChatResponse(
                    category=MessageCategory.STREAM,
                    message={
                        "content": one.content,
                        "reasoning_content": chunk_reasoning_content,
                    },
                    type="stream",
                )
                reasoning_content += chunk_reasoning_content
                answer += one.content
        except Exception as error:
            raise StreamStageError(error, stage="model", had_output=bool(answer or reasoning_content)) from error
        messages = [
            ChatMessage(
                category=MessageCategory.QUESTION,
                message=json.dumps(
                    {
                        "query": query,
                        "tags": tags,
                        "model_id": model_id,
                    },
                    ensure_ascii=False,
                ),
                chat_id=session.chat_id,
                flow_id=session.flow_id,
                user_id=self.login_user.user_id,
                type="end",
                is_bot=False,
            ),
            ChatMessage(
                category=MessageCategory.ANSWER,
                message=json.dumps({"content": answer, "reasoning_content": reasoning_content}, ensure_ascii=False),
                chat_id=session.chat_id,
                flow_id=session.flow_id,
                user_id=self.login_user.user_id,
                type="end",
                is_bot=True,
            ),
        ]
        await ChatMessageDao.ainsert_batch(messages)
        if not session.name:
            asyncio.create_task(
                self.generate_conversation(
                    user_id=self.login_user.user_id,
                    chat_id=session.chat_id,
                    question=query,
                    answer=answer,
                )
            )

        yield ChatResponse(
            category=MessageCategory.STREAM,
            message={
                "content": answer,
                "reasoning_content": reasoning_content,
            },
            type="end",
        )

    @staticmethod
    async def generate_conversation(user_id: int, chat_id: str, question: str, answer: str = None):
        llm_conf = await LLMService.get_workbench_llm()
        if not llm_conf or not llm_conf.chat_title_llm or not llm_conf.chat_title_llm.id:
            logger.debug("not found chat title llm")
            return
        llm = await LLMService.get_bisheng_llm(
            model_id=llm_conf.chat_title_llm.id,
            app_id=ApplicationTypeEnum.DAILY_CHAT.value,
            app_name="knowledge_sapce_chat_title",
            app_type=ApplicationTypeEnum.DAILY_CHAT,
            user_id=user_id,
        )
        title = await generate_conversation_title_async(question=question, llm=llm, answer=answer)
        await MessageSessionDao.update_session_name(chat_id, title)

    async def single_file_history(
        self, knowledge_id: int, file_id: int, page_size: int = 20
    ) -> list[ChatMessageHistoryResponse]:
        await self._require_file_view_permission(knowledge_id, file_id)
        flow_id = self.generate_flow_id_for_file(knowledge_id, file_id)

        session = await MessageSessionDao.afilter_session(
            flow_ids=[flow_id],
            flow_type=[FlowType.KNOLEDGE_SPACE.value],
            user_ids=[self.login_user.user_id],
            include_delete=False,
        )
        if not session:
            return []
        session = session[0]
        return await ChatSessionService.get_chat_history(session.chat_id, session.flow_id, page_size=page_size)

    async def clear_file_history(self, knowledge_id: int, file_id: int) -> bool:
        await self._require_file_view_permission(knowledge_id, file_id)
        flow_id = self.generate_flow_id_for_file(knowledge_id, file_id)
        session = await MessageSessionDao.afilter_session(
            flow_ids=[flow_id],
            flow_type=[FlowType.KNOLEDGE_SPACE.value],
            user_ids=[self.login_user.user_id],
            include_delete=False,
        )
        if not session:
            return True
        session = session[0]
        await ChatMessageDao.adelete_by_user_chat_id(chat_id=session.chat_id, user_id=self.login_user.user_id)
        return True

    async def get_chat_folder_session(self, space_id: int, folder_id: int) -> list[MessageSession]:
        """Query sessions for a specific folder_id"""
        if folder_id:
            await self._require_folder_view_permission(space_id, folder_id)
        else:
            await self._require_space_view_permission(space_id)

        flow_id = self.generate_flow_id_for_folder(space_id, folder_id)

        session = await MessageSessionDao.afilter_session(
            flow_ids=[flow_id],
            flow_type=[FlowType.KNOLEDGE_SPACE.value],
            user_ids=[self.login_user.user_id],
            include_delete=False,
        )
        return session

    async def create_chat_folder_session(self, space_id: int, folder_id: int) -> MessageSession:
        await self._require_space_view_permission(space_id)
        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space:
            raise NotFoundError(msg="Knowledge space not found for chat")
        flow_name = space.name
        if folder_id:
            folder_record = await self._require_folder_view_permission(space_id, folder_id)
            flow_name = f"{flow_name}-{folder_record.file_name}"
        flow_id = self.generate_flow_id_for_folder(space_id, folder_id)
        session = await MessageSessionDao.async_insert_one(
            MessageSession(
                chat_id=generate_uuid(),
                flow_id=flow_id,
                flow_type=FlowType.KNOLEDGE_SPACE.value,
                flow_name=f"Knowledge Space Dir: {flow_name}",
                user_id=self.login_user.user_id,
            )
        )
        return session

    async def delete_chat_folder_session(self, space_id: int, folder_id: int, chat_id: str) -> bool:
        if folder_id:
            await self._require_folder_view_permission(space_id, folder_id)
        else:
            await self._require_space_view_permission(space_id)
        flow_id = self.generate_flow_id_for_folder(space_id, folder_id)
        session = await MessageSessionDao.afilter_session(
            chat_ids=[chat_id],
            flow_ids=[flow_id],
            flow_type=[FlowType.KNOLEDGE_SPACE.value],
            user_ids=[self.login_user.user_id],
            include_delete=False,
        )
        if session:
            await MessageSessionDao.delete_session(chat_id=chat_id)
        return True

    async def get_chat_folder_history(
        self, space_id: int, folder_id: int, chat_id: str, page_size: int = 20
    ) -> list[ChatMessageHistoryResponse]:
        if folder_id:
            await self._require_folder_view_permission(space_id, folder_id)
        else:
            await self._require_space_view_permission(space_id)
        flow_id = self.generate_flow_id_for_folder(space_id, folder_id)
        return await ChatSessionService.get_chat_history(chat_id, flow_id, page_size=page_size)

    async def delete_chat_folder_history(self, space_id: int, folder_id: int, chat_id: str) -> bool:
        if folder_id:
            await self._require_folder_view_permission(space_id, folder_id)
        else:
            await self._require_space_view_permission(space_id)
        flow_id = self.generate_flow_id_for_folder(space_id, folder_id)
        session = await MessageSessionDao.afilter_session(
            chat_ids=[chat_id],
            flow_ids=[flow_id],
            flow_type=[FlowType.KNOLEDGE_SPACE.value],
            user_ids=[self.login_user.user_id],
            include_delete=False,
        )
        if not session:
            return True
        session = session[0]
        await ChatMessageDao.adelete_by_user_chat_id(chat_id=session.chat_id, user_id=self.login_user.user_id)
        return True

    async def _build_folder_search_kwargs(
        self,
        knowledge_id: int,
        target_file_ids: list[int] | None,
    ) -> tuple[dict | None, dict | None]:
        """Compute Milvus and ES search_kwargs with primary-version-only filtering.

        Args:
            knowledge_id: the knowledge space id being queried.
            target_file_ids: None means "whole space"; a list (possibly empty) means
                "specific files" derived from folder/tag resolution.

        Returns:
            (milvus_search_kwargs, es_search_kwargs)
            Both are None when target_file_ids is non-None but empty (caller should
            skip retriever construction).
        """
        # Fetch non-primary file ids once, used in both branches.
        excluded: list[int] = await self.version_repo.find_non_primary_file_ids_by_knowledge_ids([knowledge_id])
        from bisheng.knowledge.domain.services.knowledge_recycle_service import KnowledgeRecycleService

        recycled = await KnowledgeRecycleService.list_recycled_file_ids(knowledge_id)
        if recycled:
            excluded = list(dict.fromkeys([*excluded, *recycled]))

        if target_file_ids is None:
            # Branch A: whole-space query — apply not-in filter when exclusions exist.
            milvus_expr, es_filter = build_primary_only_filter(excluded)
            milvus_kwargs: dict = {"k": 100, "param": {"ef": 110}}
            es_kwargs: dict = {"k": 100}
            if milvus_expr is not None:
                milvus_kwargs["expr"] = milvus_expr
            if es_filter:
                es_kwargs["filter"] = es_filter
            return milvus_kwargs, es_kwargs

        # Branch B: specific files — remove non-primary ids from the target set.
        excluded_set = set(excluded)
        effective_target = [fid for fid in target_file_ids if fid not in excluded_set]

        if not effective_target:
            # All candidates are non-primary or the set was already empty.
            return None, None

        # The in-clause already restricts to primary files; no must_not needed.
        milvus_kwargs = {
            "k": 100,
            "param": {"ef": 110},
            "expr": f"document_id in {effective_target}",
        }
        es_kwargs = {
            "k": 100,
            "filter": [{"terms": {"metadata.document_id": effective_target}}],
        }
        return milvus_kwargs, es_kwargs

    async def chat_folder(
        self,
        knowledge_id: int,
        folder_id: int,
        chat_id: str,
        query: str,
        model_id: int,
        tags: list[dict] | None = None,
    ) -> AsyncIterator[ChatResponse | StreamRetryEvent]:
        """Folder RAG query"""
        flow_id = self.generate_flow_id_for_folder(knowledge_id, folder_id)
        session = await MessageSessionDao.afilter_session(
            chat_ids=[chat_id], flow_ids=[flow_id], user_ids=[self.login_user.user_id], include_delete=False
        )
        if not session:
            raise NotFoundError(msg="Folder session not found")
        session = session[0]

        await self._require_space_view_permission(knowledge_id)
        space = await KnowledgeDao.aquery_by_id(knowledge_id)
        if not space:
            raise NotFoundError(msg="Knowledge space not found for chat")

        target_file_ids = None

        if folder_id:
            file_record = await self._require_folder_view_permission(knowledge_id, folder_id)
            if not file_record or file_record.knowledge_id != knowledge_id or file_record.file_type != 0:
                raise NotFoundError(msg="Invalid folder for chat")
            file_level_path = file_record.file_level_path + f"/{file_record.id}"

            folder_files = await SpaceFileDao.get_children_by_prefix(space.id, file_level_path)
            target_file_ids = [one.id for one in folder_files]

        if tags:
            tag_file_ids = await TagDao.aget_resources_by_tags(
                [one.get("id") for one in tags], resource_type=ResourceTypeEnum.SPACE_FILE
            )
            tag_file_ids = [int(one.resource_id) for one in tag_file_ids]

            if target_file_ids is not None:
                target_file_ids = list(set(target_file_ids) & set(tag_file_ids))
            else:
                target_file_ids = tag_file_ids

        vector_retriever, es_retriever = None, None

        milvus_kwargs, es_kwargs = await self._build_folder_search_kwargs(knowledge_id, target_file_ids)

        if milvus_kwargs is not None and es_kwargs is not None:
            # Build retrievers only when there are matching files to query.
            milvus_vector = await KnowledgeRag.init_knowledge_milvus_vectorstore(
                self.login_user.user_id, knowledge=space
            )
            es_vector = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=space)
            vector_retriever = milvus_vector.as_retriever(search_kwargs=milvus_kwargs)
            es_retriever = es_vector.as_retriever(search_kwargs=es_kwargs)

        # executeQuery(vector_retriever, es_retriever, query)
        async for one in self.space_rag(
            session,
            vector_retriever,
            es_retriever,
            query,
            model_id,
            tags,
            knowledge_id=knowledge_id,
        ):
            yield one

    async def get_space_llm_config(self, model_id: int) -> tuple[BaseChatModel, KnowledgeSpaceConfig]:
        """
        Get chat configuration (model and prompts)

        Returns:
            tuple: (model_id, subscription_config)
        """
        llm = await LLMService.get_bisheng_llm(
            model_id=model_id,
            app_id=ApplicationTypeEnum.KNOWLEDGE_SPACE.value,
            app_name=ApplicationTypeEnum.KNOWLEDGE_SPACE.value,
            app_type=ApplicationTypeEnum.KNOWLEDGE_SPACE,
            user_id=self.login_user.user_id,
        )

        # Get subscription configuration
        config = await WorkStationService.get_knowledge_space_config()
        if config is None:
            config = KnowledgeSpaceConfig()

        return llm, config

    async def _resolve_kb_target_file_ids(
        self,
        knowledge_id: int,
        tag_names: list[str],
    ) -> list[int] | None:
        """Map a list of tag names (scoped to a knowledge space) to file ids.

        Returns ``None`` when no tag filter is requested (caller treats as
        whole-space). Returns an empty list when tags are provided but resolve
        to no files (caller short-circuits and skips this KB).
        """
        if not tag_names:
            return None

        resolved_tag_ids: list[int] = []
        for tag_name in tag_names:
            resolved_tag_ids.extend(
                await TagLibraryTagService.resolve_tag_ids_by_name_for_space(knowledge_id, tag_name)
            )
        if not resolved_tag_ids:
            return []

        tag_links = await TagDao.aget_resources_by_tags(
            resolved_tag_ids,
            resource_type=ResourceTypeEnum.SPACE_FILE,
        )
        return [int(link.resource_id) for link in tag_links]

    async def aretrieve_chunks(
        self,
        *,
        query: str,
        knowledge_base_ids: list[int],
        kb_filters: dict[int, dict[str, Any]] | None = None,
        top_k: int = 10,
        max_content: int = 15000,
        skip_unauthorized: bool = False,
    ) -> list[tuple[int, Document]]:
        """Retrieve chunks across one or more knowledge bases without LLM generation.

        Args:
            query: User question.
            knowledge_base_ids: Knowledge space ids to search.
            kb_filters: Optional ``{kb_id: {"tags": [name, ...], "tag_match_mode": "ANY"}}``
                entries used to narrow each KB by tag. ``tag_match_mode`` other than
                ``"ANY"`` raises HTTP 400.
            top_k: Hard cap on returned chunks across all KBs.
            max_content: Per-KB combined-content size limit handed to KnowledgeRetrieverTool.
            skip_unauthorized: Skip knowledge spaces that the permission subject cannot view.

        Returns:
            Up to ``top_k`` ``(knowledge_id, Document)`` pairs.
        """
        if not knowledge_base_ids:
            raise HTTPException(status_code=400, detail="knowledge_base_ids must not be empty")

        kb_id_set = set(knowledge_base_ids)
        filters_by_kb: dict[int, dict[str, Any]] = {}
        if kb_filters:
            for kb_id, spec in kb_filters.items():
                if kb_id not in kb_id_set:
                    raise HTTPException(
                        status_code=400,
                        detail=f"filter references kb_id {kb_id} not present in knowledge_base_ids",
                    )
                mode = (spec or {}).get("tag_match_mode", "ANY")
                if mode != "ANY":
                    raise HTTPException(
                        status_code=400,
                        detail="tag_match_mode=ALL is not yet supported",
                    )
                filters_by_kb[kb_id] = spec

        per_kb_results = await asyncio.gather(
            *(
                self._aretrieve_chunks_for_kb(
                    kb_id,
                    query=query,
                    tag_names=(filters_by_kb.get(kb_id) or {}).get("tags") or [],
                    file_ids=(filters_by_kb.get(kb_id) or {}).get("file_ids"),
                    max_content=max_content,
                )
                for kb_id in knowledge_base_ids
            ),
            return_exceptions=skip_unauthorized,
        )

        flattened: list[tuple[int, Document]] = []
        for kb_id, chunks in zip(knowledge_base_ids, per_kb_results, strict=True):
            if isinstance(chunks, SpacePermissionDeniedError) and skip_unauthorized:
                logger.info(
                    "skip unauthorized knowledge space during retrieval: user_id={} space_id={}",
                    self.login_user.user_id,
                    kb_id,
                )
                continue
            if isinstance(chunks, BaseException):
                raise chunks
            flattened.extend(chunks)
        return self._dedupe_cross_knowledge_chunks(flattened)[:top_k]

    async def _aretrieve_chunks_for_kb(
        self,
        kb_id: int,
        *,
        query: str,
        tag_names: list[str],
        file_ids: list[int] | None = None,
        max_content: int,
    ) -> list[tuple[int, Document]]:
        """Retrieve chunks for a single knowledge base. Raises NotFoundError if missing."""
        await self._require_space_view_permission(kb_id)
        space = await KnowledgeDao.aquery_by_id(kb_id)
        if not space:
            raise NotFoundError(msg=f"Knowledge base {kb_id} not found")

        target_file_ids = await self._resolve_kb_target_file_ids(kb_id, tag_names)
        if tag_names and not target_file_ids:
            return []
        if file_ids is not None:
            scoped_file_ids = [int(file_id) for file_id in file_ids if str(file_id).isdigit() and int(file_id) > 0]
            if target_file_ids is None:
                target_file_ids = scoped_file_ids
            else:
                target_file_ids = list(set(target_file_ids) & set(scoped_file_ids))
            if not target_file_ids:
                return []

        milvus_kwargs, es_kwargs = await self._build_folder_search_kwargs(kb_id, target_file_ids)
        if milvus_kwargs is None and es_kwargs is None:
            return []

        milvus_vector = await KnowledgeRag.init_knowledge_milvus_vectorstore(self.login_user.user_id, knowledge=space)
        es_vector = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=space)
        vector_retriever = milvus_vector.as_retriever(search_kwargs=milvus_kwargs)
        es_retriever = es_vector.as_retriever(search_kwargs=es_kwargs)

        docs = await self._retrieve_visible_documents(
            query=query,
            vector_retriever=vector_retriever,
            es_retriever=es_retriever,
            max_content=max_content,
            sort_by_source_and_index=False,
            knowledge_id=kb_id,
        )
        return [(kb_id, d) for d in docs]

    @staticmethod
    def _canonical_metadata(document: Document) -> tuple[dict[str, Any], dict[str, Any]]:
        metadata = dict(document.metadata or {})
        user_metadata = metadata.get("user_metadata")
        return metadata, user_metadata if isinstance(user_metadata, dict) else {}

    @classmethod
    def _canonical_chunk_key(cls, document: Document) -> tuple[Any, Any, int]:
        metadata, canonical_metadata = cls._canonical_metadata(document)
        document_id = (
            metadata.get("canonical_document_id")
            or canonical_metadata.get("canonical_document_id")
            or metadata.get("document_id")
            or metadata.get("file_id")
            or metadata.get("source")
            or metadata.get("document_name")
            or id(document)
        )
        version_id = (
            metadata.get("canonical_version_id")
            or canonical_metadata.get("canonical_version_id")
            or document_id
        )
        chunk_index = metadata.get("chunk_index")
        if chunk_index is None:
            chunk_index = canonical_metadata.get("chunk_index", 0)
        try:
            normalized_chunk_index = int(chunk_index or 0)
        except (TypeError, ValueError):
            normalized_chunk_index = 0
        return document_id, version_id, normalized_chunk_index

    @classmethod
    def _dedupe_cross_knowledge_chunks(
        cls,
        chunks: list[tuple[int, Document]],
    ) -> list[tuple[int, Document]]:
        seen: set[tuple[Any, Any, int]] = set()
        output: list[tuple[int, Document]] = []
        for knowledge_id, document in chunks:
            key = cls._canonical_chunk_key(document)
            if key in seen:
                continue
            seen.add(key)
            output.append((knowledge_id, document))
        return output

    @staticmethod
    def _metadata_int(
        metadata: dict[str, Any],
        canonical_metadata: dict[str, Any],
        key: str,
    ) -> int:
        value = metadata.get(key)
        if value is None:
            value = canonical_metadata.get(key)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    async def _filter_visible_projection_documents(
        self,
        documents: list[Document],
        *,
        knowledge_id: int,
        preauthorized_file_ids: set[int] | None = None,
    ) -> list[Document]:
        if not documents:
            return []

        parsed_documents: list[
            tuple[Document, dict[str, Any], dict[str, Any], int]
        ] = []
        for document in documents:
            metadata, canonical_metadata = self._canonical_metadata(document)
            file_id = self._metadata_int(
                metadata,
                canonical_metadata,
                "document_id",
            ) or self._metadata_int(metadata, canonical_metadata, "file_id")
            if file_id > 0:
                parsed_documents.append(
                    (document, metadata, canonical_metadata, file_id)
                )
        if not parsed_documents:
            return []

        files = await KnowledgeFileDao.aget_file_by_ids(
            sorted({item[3] for item in parsed_documents})
        )
        file_map = {
            int(file.id): file
            for file in files
            if int(file.knowledge_id) == int(knowledge_id)
            and int(file.file_type) == FileType.FILE.value
            and int(file.status) == KnowledgeFileStatus.SUCCESS.value
        }

        preauthorized = {
            int(file_id) for file_id in (preauthorized_file_ids or set())
        }
        visible_file_ids = set(preauthorized) & set(file_map)
        for file_id, file in file_map.items():
            if file_id in visible_file_ids:
                continue
            try:
                await self._require_file_view_permission(
                    int(file.knowledge_id),
                    file_id,
                )
            except (NotFoundError, SpacePermissionDeniedError):
                continue
            visible_file_ids.add(file_id)

        document_ids = sorted(
            {
                int(file.reference_document_id)
                for file_id, file in file_map.items()
                if file_id in visible_file_ids
                and file.reference_document_id is not None
            }
        )
        document_map = {}
        if document_ids and self.doc_repo is not None:
            canonical_documents = await self.doc_repo.find_by_ids(document_ids)
            document_map = {
                int(document.id): document
                for document in canonical_documents
                if document.id is not None
            }

        output: list[Document] = []
        for document, metadata, canonical_metadata, file_id in parsed_documents:
            file = file_map.get(file_id)
            if file is None or file_id not in visible_file_ids:
                continue
            if file.reference_document_id is None:
                output.append(document)
                continue

            canonical_document = document_map.get(
                int(file.reference_document_id)
            )
            if canonical_document is None:
                continue
            if (
                file.entry_status != KnowledgeFileEntryStatus.ACTIVE.value
                or file.entry_type
                not in {
                    KnowledgeFileEntryType.MANAGER.value,
                    KnowledgeFileEntryType.PUBLISH.value,
                    KnowledgeFileEntryType.SHARE.value,
                }
                or file.projection_status
                != KnowledgeFileProjectionStatus.READY.value
                or int(file.applied_content_generation)
                < int(file.desired_content_generation)
                or int(file.applied_entry_generation)
                < int(file.desired_entry_generation)
            ):
                continue

            canonical_document_id = self._metadata_int(
                metadata,
                canonical_metadata,
                "canonical_document_id",
            )
            canonical_version_id = self._metadata_int(
                metadata,
                canonical_metadata,
                "canonical_version_id",
            )
            content_generation = self._metadata_int(
                metadata,
                canonical_metadata,
                "content_generation",
            )
            entry_generation = self._metadata_int(
                metadata,
                canonical_metadata,
                "entry_generation",
            )
            if (
                canonical_document_id != int(file.reference_document_id)
                or canonical_document.primary_version_id is None
                or canonical_version_id
                != int(canonical_document.primary_version_id)
                or content_generation
                != int(file.desired_content_generation)
                or entry_generation != int(file.desired_entry_generation)
            ):
                continue
            output.append(document)
        return output

    async def _retrieve_visible_documents(
        self,
        *,
        query: str,
        vector_retriever,
        es_retriever,
        max_content: int,
        sort_by_source_and_index: bool,
        knowledge_id: int | None,
        preauthorized_file_ids: set[int] | None = None,
    ) -> list[Document]:
        vector_documents: list[Document] = []
        es_documents: list[Document] = []
        if vector_retriever is not None:
            vector_documents = await asyncio.to_thread(
                vector_retriever.invoke,
                query,
            )
        if es_retriever is not None:
            es_documents = await es_retriever.ainvoke(query)

        if knowledge_id is not None:
            tagged_documents = [
                Document(
                    page_content=document.page_content,
                    metadata={
                        **dict(document.metadata or {}),
                        "__f059_retriever": retriever,
                    },
                )
                for retriever, documents in (
                    ("vector", vector_documents),
                    ("elastic", es_documents),
                )
                for document in documents
            ]
            visible_documents = await self._filter_visible_projection_documents(
                tagged_documents,
                knowledge_id=knowledge_id,
                preauthorized_file_ids=preauthorized_file_ids,
            )
            vector_documents = []
            es_documents = []
            for document in visible_documents:
                metadata = dict(document.metadata or {})
                retriever = metadata.pop("__f059_retriever", None)
                visible_document = Document(
                    page_content=document.page_content,
                    metadata=metadata,
                )
                if retriever == "vector":
                    vector_documents.append(visible_document)
                elif retriever == "elastic":
                    es_documents.append(visible_document)

        retriever_tool = KnowledgeRetrieverTool(
            vector_retriever=vector_retriever,
            elastic_retriever=es_retriever,
            max_content=max_content,
            sort_by_source_and_index=sort_by_source_and_index,
        )
        return retriever_tool._rrf_rerank(
            vector_documents,
            es_documents,
            query,
        )

    @staticmethod
    async def get_history(chat_id: str, limit: int = 4) -> list[BaseMessage]:
        res = await ChatMessageDao.aget_messages_by_chat_id(chat_id, ["question", "answer"], limit=limit)
        messages = []
        for one in res:
            if one.category == MessageCategory.QUESTION:
                content = json.loads(one.message).get("query")
                messages.append(HumanMessage(content=content))
            else:
                answer = json.loads(one.message).get("content")
                messages.append(AIMessage(content=answer))
        return messages
