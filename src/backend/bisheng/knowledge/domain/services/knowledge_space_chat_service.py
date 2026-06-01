import asyncio
import json
from datetime import datetime
from typing import List, Optional, AsyncIterator, Tuple, Dict, Any

from fastapi import HTTPException, Request
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from loguru import logger

from bisheng.api.services.workstation import WorkStationService
from bisheng.api.v1.schema.chat_schema import ChatMessageHistoryResponse
from bisheng.api.v1.schemas import ChatResponse, KnowledgeSpaceConfig
from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.utils.title_generator import generate_conversation_title_async
from bisheng.core.prompts.manager import get_prompt_manager
from bisheng.database.constants import MessageCategory
from bisheng.database.models.flow import FlowType
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.message import ChatMessageDao, ChatMessage
from bisheng.database.models.session import MessageSessionDao, MessageSession
from bisheng.database.models.tag import TagBusinessTypeEnum, TagDao
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao
from bisheng.knowledge.rag.version_filter import build_primary_only_filter
from bisheng.llm.domain.utils import extract_reasoning_content
from bisheng.llm.domain import LLMService
from bisheng.tool.domain.langchain.knowledge import KnowledgeRetrieverTool
from bisheng.utils import generate_uuid


class KnowledgeSpaceChatService:
    """ Service class for handling Knowledge Space AI Chat operations """

    def __init__(self, request: Request, login_user: UserPayload):
        self.request = request
        self.login_user = login_user

    def _permission_service(self):
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

        if not hasattr(self, '_knowledge_space_permission_service'):
            self._knowledge_space_permission_service = KnowledgeSpaceService(self.request, self.login_user)
        return self._knowledge_space_permission_service

    def _visibility_service(self):
        """F029: lazy KnowledgeFileVisibilityService for the two-layer view_file filter."""
        from bisheng.knowledge.domain.services.knowledge_file_visibility_service import (
            KnowledgeFileVisibilityService,
        )

        if not hasattr(self, '_knowledge_file_visibility_service'):
            svc = KnowledgeFileVisibilityService(self.request, self.login_user)
            svc.version_repo = getattr(self, 'version_repo', None)
            self._knowledge_file_visibility_service = svc
        return self._knowledge_file_visibility_service

    def _qa_filter_conf(self):
        """F029 retrieval-loop config (multipliers, base k)."""
        try:
            from bisheng.common.services.config_service import settings

            return settings.knowledge_qa_filter
        except (AttributeError, ImportError):
            from bisheng.core.config.settings import KnowledgeQAFilterConf

            return KnowledgeQAFilterConf()

    async def _require_space_view_permission(self, space_id: int):
        svc = self._permission_service()
        await svc._require_read_permission(space_id)
        await svc._require_permission_id('knowledge_space', space_id, 'view_space')

    async def _require_folder_view_permission(self, space_id: int, folder_id: int):
        svc = self._permission_service()
        folder = await svc._require_folder_relation(space_id, folder_id, 'can_read')
        await svc._require_permission_id('folder', folder_id, 'view_folder', space_id=space_id)
        return folder

    async def _require_file_view_permission(self, space_id: int, file_id: int):
        svc = self._permission_service()
        file_record = await svc._require_file_relation(file_id, 'can_read', space_id=space_id)
        await svc._require_permission_id('knowledge_file', file_id, 'view_file', space_id=space_id)
        return file_record

    @classmethod
    def generate_flow_id_for_file(cls, knowledge_id: int, file_id: int) -> str:
        """ Generate a unique flow_id representation for a single file chat """
        return f"space_{knowledge_id}_file_{file_id}"

    @classmethod
    def generate_flow_id_for_folder(cls, knowledge_id: int, folder_id: int = 0) -> str:
        """ Generate a unique flow_id representation for a folder chat """
        return f"space_{knowledge_id}_folder_{folder_id}"

    async def chat_single_file(self, knowledge_id: int, file_id: int, query: str,
                               model_id: int) \
            -> AsyncIterator[ChatResponse]:
        """ Single file RAG query """
        # Verify file exists and is a file
        file_record = await self._require_file_view_permission(knowledge_id, file_id)
        # F029/AC-09: trace that the view_file gate passed; the document_id == file_id
        # filter on the retriever guarantees no chunks from other files can leak.
        logger.debug(
            "chat_single_file: view_file check passed | file_id={} space_id={}",
            file_id,
            knowledge_id,
        )

        space = await KnowledgeDao.aquery_by_id(file_record.knowledge_id)
        if not space:
            raise NotFoundError(msg="Knowledge space not found for chat")

        flow_id = self.generate_flow_id_for_file(knowledge_id, file_id)

        session = await MessageSessionDao.afilter_session(flow_ids=[flow_id],
                                                          flow_type=[FlowType.KNOLEDGE_SPACE.value],
                                                          user_ids=[self.login_user.user_id],
                                                          include_delete=False)
        if not session:
            session = await MessageSessionDao.async_insert_one(MessageSession(
                chat_id=generate_uuid(),
                flow_id=flow_id,
                flow_name=file_record.file_name,
                flow_type=FlowType.KNOLEDGE_SPACE.value,
                user_id=self.login_user.user_id,
            ))
        else:
            session = session[0]

        milvus_vector = await KnowledgeRag.init_knowledge_milvus_vectorstore(self.login_user.user_id, knowledge=space)
        vector_retriever = milvus_vector.as_retriever(search_kwargs={
            "k": 100,
            "param": {"ef": 110},
            "expr": f"document_id == {file_id}"
        })
        es_vector = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=space)
        es_retriever = es_vector.as_retriever(search_kwargs={
            "filter": [{"term": {"metadata.document_id": file_id}}]
        })
        async for one in self.space_rag(session, vector_retriever, es_retriever, query, model_id, None):
            yield one

    async def space_rag(self, session, vector_retriever, es_retriever, query: str, model_id: int, tags: Any = None) \
            -> AsyncIterator[ChatResponse]:
        llm, space_conf = await self.get_space_llm_config(model_id=model_id)

        retriever_tool = KnowledgeRetrieverTool(
            vector_retriever=vector_retriever,
            elastic_retriever=es_retriever,
            max_content=space_conf.max_chunk_size,
            sort_by_source_and_index=True
        )
        finally_docs: List[Document] = await retriever_tool.ainvoke(query)
        logger.debug(f"retrieved_finally_docs: {len(finally_docs)}")
        file_content = ""
        for one in finally_docs:
            file_content += one.page_content + "\n"

        prompt_service = await get_prompt_manager()

        if space_conf.system_prompt:
            inputs = [
                SystemMessage(content=space_conf.system_prompt.format(cur_date=datetime.now().strftime('%Y-%m-%d'))),
                HumanMessage(
                    content=space_conf.user_prompt.format(retrieved_file_content=file_content, question=query)),
            ]
        else:
            prompt_obj = prompt_service.render_prompt(
                namespace="knowledge_space",
                prompt_name="rag_prompt",
                cur_date=datetime.now().strftime('%Y-%m-%d'),
                retrieved_file_content=file_content,
                question=query
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

        async for one in llm.astream(inputs):
            chunk_reasoning_content = extract_reasoning_content(one)
            yield ChatResponse(
                category=MessageCategory.STREAM,
                message={
                    "content": one.content,
                    "reasoning_content": chunk_reasoning_content,
                },
                type="stream"
            )
            reasoning_content += chunk_reasoning_content
            answer += one.content
        messages = [
            ChatMessage(
                category=MessageCategory.QUESTION,
                message=json.dumps({
                    "query": query,
                    "tags": tags,
                    "model_id": model_id,
                }, ensure_ascii=False),
                chat_id=session.chat_id,
                flow_id=session.flow_id,
                user_id=self.login_user.user_id,
                type="end",
                is_bot=False,
            ),
            ChatMessage(
                category=MessageCategory.ANSWER,
                message=json.dumps({
                    "content": answer,
                    "reasoning_content": reasoning_content
                }, ensure_ascii=False),
                chat_id=session.chat_id,
                flow_id=session.flow_id,
                user_id=self.login_user.user_id,
                type="end",
                is_bot=True,
            )
        ]
        await ChatMessageDao.ainsert_batch(messages)
        if not session.name:
            asyncio.create_task(self.generate_conversation(
                user_id=self.login_user.user_id,
                chat_id=session.chat_id,
                question=query,
                answer=answer,
            ))

        yield ChatResponse(
            category=MessageCategory.STREAM,
            message={
                "content": answer,
                "reasoning_content": reasoning_content,
            },
            type="end"
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
            app_name='knowledge_sapce_chat_title',
            app_type=ApplicationTypeEnum.DAILY_CHAT,
            user_id=user_id
        )
        title = await generate_conversation_title_async(question=question, llm=llm, answer=answer)
        await MessageSessionDao.update_session_name(chat_id, title)

    async def single_file_history(self, knowledge_id: int, file_id: int, page_size: int = 20) \
            -> List[ChatMessageHistoryResponse]:
        await self._require_file_view_permission(knowledge_id, file_id)
        flow_id = self.generate_flow_id_for_file(knowledge_id, file_id)

        session = await MessageSessionDao.afilter_session(flow_ids=[flow_id],
                                                          flow_type=[FlowType.KNOLEDGE_SPACE.value],
                                                          user_ids=[self.login_user.user_id],
                                                          include_delete=False)
        if not session:
            return []
        session = session[0]
        return await ChatSessionService.get_chat_history(session.chat_id, session.flow_id, page_size=page_size)

    async def clear_file_history(self, knowledge_id: int, file_id: int) -> bool:
        await self._require_file_view_permission(knowledge_id, file_id)
        flow_id = self.generate_flow_id_for_file(knowledge_id, file_id)
        session = await MessageSessionDao.afilter_session(flow_ids=[flow_id],
                                                          flow_type=[FlowType.KNOLEDGE_SPACE.value],
                                                          user_ids=[self.login_user.user_id],
                                                          include_delete=False)
        if not session:
            return True
        session = session[0]
        await ChatMessageDao.adelete_by_user_chat_id(chat_id=session.chat_id, user_id=self.login_user.user_id)
        return True

    async def get_chat_folder_session(self, space_id: int, folder_id: int) -> List[MessageSession]:
        """ Query sessions for a specific folder_id """
        if folder_id:
            await self._require_folder_view_permission(space_id, folder_id)
        else:
            await self._require_space_view_permission(space_id)

        flow_id = self.generate_flow_id_for_folder(space_id, folder_id)

        session = await MessageSessionDao.afilter_session(flow_ids=[flow_id],
                                                          flow_type=[FlowType.KNOLEDGE_SPACE.value],
                                                          user_ids=[self.login_user.user_id],
                                                          include_delete=False)
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
        session = await MessageSessionDao.async_insert_one(MessageSession(
            chat_id=generate_uuid(),
            flow_id=flow_id,
            flow_type=FlowType.KNOLEDGE_SPACE.value,
            flow_name=f"Knowledge Space Dir: {flow_name}",
            user_id=self.login_user.user_id,
        ))
        return session

    async def delete_chat_folder_session(self, space_id: int, folder_id: int, chat_id: str) -> bool:
        if folder_id:
            await self._require_folder_view_permission(space_id, folder_id)
        else:
            await self._require_space_view_permission(space_id)
        flow_id = self.generate_flow_id_for_folder(space_id, folder_id)
        session = await MessageSessionDao.afilter_session(chat_ids=[chat_id],
                                                          flow_ids=[flow_id],
                                                          flow_type=[FlowType.KNOLEDGE_SPACE.value],
                                                          user_ids=[self.login_user.user_id],
                                                          include_delete=False)
        if session:
            await MessageSessionDao.delete_session(chat_id=chat_id)
        return True

    async def get_chat_folder_history(self, space_id: int, folder_id: int, chat_id: str, page_size: int = 20) \
            -> List[ChatMessageHistoryResponse]:
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
        session = await MessageSessionDao.afilter_session(chat_ids=[chat_id],
                                                          flow_ids=[flow_id],
                                                          flow_type=[FlowType.KNOLEDGE_SPACE.value],
                                                          user_ids=[self.login_user.user_id],
                                                          include_delete=False)
        if not session:
            return True
        session = session[0]
        await ChatMessageDao.adelete_by_user_chat_id(chat_id=session.chat_id, user_id=self.login_user.user_id)
        return True

    async def _build_folder_search_kwargs(
        self,
        knowledge_id: int,
        target_file_ids: Optional[List[int]],
    ) -> Tuple[Optional[dict], Optional[dict]]:
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
        excluded: List[int] = await self.version_repo.find_non_primary_file_ids_by_knowledge_ids(
            [knowledge_id]
        )

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

    async def _retrieve_and_filter(
        self,
        *,
        space,
        query: str,
        candidate_file_ids: Optional[List[int]],
        max_content: int,
    ) -> List[Document]:
        """F029: two-layer view_file filter retrieval loop (AD-01 / AD-03).

        Returns docs whose ``document_id`` belongs to a file the current user
        has ``view_file`` on. Caps at two retrieval attempts; emits one
        structured ``permission_filter`` log line per attempt (AC-27).
        """
        visibility = self._visibility_service()
        conf = self._qa_filter_conf()

        index_filter = await visibility.build_index_prefilter(
            space.id, candidate_file_ids
        )
        if index_filter.is_empty:
            logger.info(
                "permission_filter | space_id={} strategy=empty accessible_ids_size={} "
                "prefilter_candidate_size=0 retrieval_attempts=0 post_filter_dropped_count=0",
                space.id,
                index_filter.accessible_size,
            )
            return []

        base_milvus_expr = index_filter.milvus_expr
        base_es_filter = index_filter.es_filter or []
        multipliers = (
            conf.retrieval_initial_multiplier,
            conf.retrieval_expansion_multiplier,
        )

        survivors: List[Document] = []
        for attempt_idx, multiplier in enumerate(multipliers, start=1):
            base_k = 100  # current retrieval default; multiplier scales it
            milvus_kwargs: Dict[str, Any] = {
                "k": base_k * multiplier,
                "param": {"ef": 110},
            }
            if base_milvus_expr:
                milvus_kwargs["expr"] = base_milvus_expr
            es_kwargs: Dict[str, Any] = {"k": base_k * multiplier}
            if base_es_filter:
                es_kwargs["filter"] = base_es_filter

            milvus_vector = await KnowledgeRag.init_knowledge_milvus_vectorstore(
                self.login_user.user_id, knowledge=space
            )
            es_vector = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=space)
            vector_retriever = milvus_vector.as_retriever(search_kwargs=milvus_kwargs)
            es_retriever = es_vector.as_retriever(search_kwargs=es_kwargs)

            retriever_tool = KnowledgeRetrieverTool(
                vector_retriever=vector_retriever,
                elastic_retriever=es_retriever,
                max_content=max_content,
                sort_by_source_and_index=True,
            )
            docs: List[Document] = await retriever_tool.ainvoke(query)

            unique_file_ids = {
                int(d.metadata.get("document_id"))
                for d in docs
                if d.metadata and d.metadata.get("document_id") is not None
            }
            permitted = await visibility.post_filter_visible_files(
                space.id, unique_file_ids
            )
            survivors = [
                d
                for d in docs
                if int(d.metadata.get("document_id", -1)) in permitted
            ]
            dropped = len(docs) - len(survivors)

            logger.info(
                "permission_filter | space_id={} strategy={} accessible_ids_size={} "
                "prefilter_candidate_size={} retrieval_attempts={} "
                "post_filter_dropped_count={}",
                space.id,
                index_filter.strategy,
                index_filter.accessible_size,
                len(docs),
                attempt_idx,
                dropped,
            )

            if survivors:
                break  # AD-03: stop on first non-empty attempt

        return survivors

    async def _render_rag_response(
        self,
        session,
        finally_docs: List[Document],
        query: str,
        model_id: int,
        tags: Any = None,
    ) -> AsyncIterator[ChatResponse]:
        """F029: prompt rendering + LLM streaming, given pre-fetched docs.

        Extracted from ``space_rag`` so ``chat_folder`` can drive retrieval via
        ``_retrieve_and_filter`` while reusing the unchanged prompt + stream path.
        """
        llm, space_conf = await self.get_space_llm_config(model_id=model_id)
        logger.debug(f"retrieved_finally_docs: {len(finally_docs)}")
        file_content = ""
        for one in finally_docs:
            file_content += one.page_content + "\n"

        prompt_service = await get_prompt_manager()

        if space_conf.system_prompt:
            inputs = [
                SystemMessage(content=space_conf.system_prompt.format(cur_date=datetime.now().strftime('%Y-%m-%d'))),
                HumanMessage(
                    content=space_conf.user_prompt.format(retrieved_file_content=file_content, question=query)),
            ]
        else:
            prompt_obj = prompt_service.render_prompt(
                namespace="knowledge_space",
                prompt_name="rag_prompt",
                cur_date=datetime.now().strftime('%Y-%m-%d'),
                retrieved_file_content=file_content,
                question=query
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

        async for one in llm.astream(inputs):
            chunk_reasoning_content = extract_reasoning_content(one)
            yield ChatResponse(
                category=MessageCategory.STREAM,
                message={
                    "content": one.content,
                    "reasoning_content": chunk_reasoning_content,
                },
                type="stream"
            )
            reasoning_content += chunk_reasoning_content
            answer += one.content
        messages = [
            ChatMessage(
                category=MessageCategory.QUESTION,
                message=json.dumps({
                    "query": query,
                    "tags": tags,
                    "model_id": model_id,
                }, ensure_ascii=False),
                chat_id=session.chat_id,
                flow_id=session.flow_id,
                user_id=self.login_user.user_id,
                type="end",
                is_bot=False,
            ),
            ChatMessage(
                category=MessageCategory.ANSWER,
                message=json.dumps({
                    "content": answer,
                    "reasoning_content": reasoning_content
                }, ensure_ascii=False),
                chat_id=session.chat_id,
                flow_id=session.flow_id,
                user_id=self.login_user.user_id,
                type="end",
                is_bot=True,
            )
        ]
        await ChatMessageDao.ainsert_batch(messages)
        if not session.name:
            asyncio.create_task(self.generate_conversation(
                user_id=self.login_user.user_id,
                chat_id=session.chat_id,
                question=query,
                answer=answer,
            ))

        yield ChatResponse(
            category=MessageCategory.STREAM,
            message={
                "content": answer,
                "reasoning_content": reasoning_content,
            },
            type="end"
        )

    async def chat_folder(self, knowledge_id: int, folder_id: int, chat_id: str, query: str,
                          model_id: int, tags: Optional[List[Dict]] = None) -> AsyncIterator[ChatResponse]:
        """ Folder RAG query """
        flow_id = self.generate_flow_id_for_folder(knowledge_id, folder_id)
        session = await MessageSessionDao.afilter_session(chat_ids=[chat_id],
                                                          flow_ids=[flow_id],
                                                          user_ids=[self.login_user.user_id],
                                                          include_delete=False)
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
            tag_file_ids = await TagDao.aget_resources_by_tags([one.get("id") for one in tags],
                                                               resource_type=ResourceTypeEnum.SPACE_FILE)
            tag_file_ids = [int(one.resource_id) for one in tag_file_ids]

            if target_file_ids is not None:
                target_file_ids = list(set(target_file_ids) & set(tag_file_ids))
            else:
                target_file_ids = tag_file_ids

        # F029: two-layer view_file filter retrieval (AD-01 / AD-02 / AD-03).
        # `_retrieve_and_filter` consults KnowledgeFileVisibilityService for
        # both the index-layer IN/NOT-IN/none strategy and the result-layer
        # view_file post-filter, returning only chunks from files the user can
        # see in the list UI.
        _, space_conf = await self.get_space_llm_config(model_id=model_id)
        finally_docs = await self._retrieve_and_filter(
            space=space,
            query=query,
            candidate_file_ids=target_file_ids,
            max_content=space_conf.max_chunk_size,
        )

        async for one in self._render_rag_response(
            session, finally_docs, query, model_id, tags
        ):
            yield one

    async def get_space_llm_config(self, model_id: int) -> Tuple[BaseChatModel, KnowledgeSpaceConfig]:
        """
        Get chat configuration (model and prompts)

        Returns:
            tuple: (model_id, subscription_config)
        """
        llm = await LLMService.get_bisheng_llm(model_id=model_id,
                                               app_id=ApplicationTypeEnum.KNOWLEDGE_SPACE.value,
                                               app_name=ApplicationTypeEnum.KNOWLEDGE_SPACE.value,
                                               app_type=ApplicationTypeEnum.KNOWLEDGE_SPACE,
                                               user_id=self.login_user.user_id)

        # Get subscription configuration
        config = await WorkStationService.get_knowledge_space_config()
        if config is None:
            config = KnowledgeSpaceConfig()

        return llm, config

    async def _resolve_kb_target_file_ids(
        self,
        knowledge_id: int,
        tag_names: List[str],
    ) -> Optional[List[int]]:
        """Map a list of tag names (scoped to a knowledge space) to file ids.

        Returns ``None`` when no tag filter is requested (caller treats as
        whole-space). Returns an empty list when tags are provided but resolve
        to no files (caller short-circuits and skips this KB).
        """
        if not tag_names:
            return None

        resolved_tag_ids: List[int] = []
        for tag_name in tag_names:
            tags = await TagDao.get_tags_by_business(
                business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
                business_id=str(knowledge_id),
                name=tag_name,
            )
            resolved_tag_ids.extend([t.id for t in tags])
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
        knowledge_base_ids: List[int],
        kb_filters: Optional[Dict[int, Dict[str, Any]]] = None,
        top_k: int = 10,
        max_content: int = 15000,
    ) -> List[Tuple[int, Document]]:
        """Retrieve chunks across one or more knowledge bases without LLM generation.

        Args:
            query: User question.
            knowledge_base_ids: Knowledge space ids to search.
            kb_filters: Optional ``{kb_id: {"tags": [name, ...], "tag_match_mode": "ANY"}}``
                entries used to narrow each KB by tag. ``tag_match_mode`` other than
                ``"ANY"`` raises HTTP 400.
            top_k: Hard cap on returned chunks across all KBs.
            max_content: Per-KB combined-content size limit handed to KnowledgeRetrieverTool.

        Returns:
            Up to ``top_k`` ``(knowledge_id, Document)`` pairs.
        """
        if not knowledge_base_ids:
            raise HTTPException(status_code=400, detail="knowledge_base_ids must not be empty")

        kb_id_set = set(knowledge_base_ids)
        filters_by_kb: Dict[int, Dict[str, Any]] = {}
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
                    max_content=max_content,
                )
                for kb_id in knowledge_base_ids
            )
        )

        flattened: List[Tuple[int, Document]] = []
        for chunks in per_kb_results:
            flattened.extend(chunks)
        return flattened[:top_k]

    async def _aretrieve_chunks_for_kb(
        self,
        kb_id: int,
        *,
        query: str,
        tag_names: List[str],
        max_content: int,
    ) -> List[Tuple[int, Document]]:
        """Retrieve chunks for a single knowledge base. Raises NotFoundError if missing."""
        await self._require_space_view_permission(kb_id)
        space = await KnowledgeDao.aquery_by_id(kb_id)
        if not space:
            raise NotFoundError(msg=f"Knowledge base {kb_id} not found")

        target_file_ids = await self._resolve_kb_target_file_ids(kb_id, tag_names)
        if tag_names and not target_file_ids:
            return []

        milvus_kwargs, es_kwargs = await self._build_folder_search_kwargs(kb_id, target_file_ids)
        if milvus_kwargs is None and es_kwargs is None:
            return []

        milvus_vector = await KnowledgeRag.init_knowledge_milvus_vectorstore(
            self.login_user.user_id, knowledge=space
        )
        es_vector = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=space)
        vector_retriever = milvus_vector.as_retriever(search_kwargs=milvus_kwargs)
        es_retriever = es_vector.as_retriever(search_kwargs=es_kwargs)

        retriever_tool = KnowledgeRetrieverTool(
            vector_retriever=vector_retriever,
            elastic_retriever=es_retriever,
            max_content=max_content,
            sort_by_source_and_index=False,
        )
        docs: List[Document] = await retriever_tool.ainvoke(query)
        return [(kb_id, d) for d in docs]

    @staticmethod
    async def get_history(chat_id: str, limit: int = 4) -> List[BaseMessage]:
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
