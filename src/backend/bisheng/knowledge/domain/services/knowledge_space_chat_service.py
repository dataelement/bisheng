import asyncio
import json
from datetime import datetime
from typing import List, Optional, AsyncIterator, Tuple, Dict, Any

from fastapi import Request
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
from bisheng.common.errcode.channel import KnowledgeSpaceLLMNotConfiguredError
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.utils.title_generator import generate_conversation_title_async
from bisheng.core.prompts.manager import get_prompt_manager
from bisheng.database.constants import MessageCategory
from bisheng.database.models.flow import FlowType
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.message import ChatMessageDao, ChatMessage
from bisheng.database.models.session import MessageSessionDao, MessageSession
from bisheng.database.models.tag import TagDao
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao
from bisheng.llm.domain import LLMService
from bisheng.llm.domain.schemas import WorkbenchModelConfig
from bisheng.tool.domain.langchain.knowledge import KnowledgeRetrieverTool
from bisheng.utils import generate_uuid


class KnowledgeSpaceChatService:
    """ Service class for handling Knowledge Space AI Chat operations """

    def __init__(self, request: Request, login_user: UserPayload):
        self.request = request
        self.login_user = login_user

    @classmethod
    def generate_flow_id_for_file(cls, knowledge_id: int, file_id: int) -> str:
        """ Generate a unique flow_id representation for a single file chat """
        return f"space_{knowledge_id}_file_{file_id}"

    @classmethod
    def generate_flow_id_for_folder(cls, knowledge_id: int, folder_id: int = 0) -> str:
        """ Generate a unique flow_id representation for a folder chat """
        return f"space_{knowledge_id}_folder_{folder_id}"

    async def chat_single_file(self, knowledge_id: int, file_id: int, query: str) \
            -> AsyncIterator[ChatResponse]:
        """ Single file RAG query """
        # Verify file exists and is a file
        file_record = await KnowledgeFileDao.query_by_id(file_id)
        if not file_record or file_record.knowledge_id != knowledge_id or file_record.file_type != 1:
            raise NotFoundError(msg="Invalid file for chat")

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
        async for one in self.space_rag(session, vector_retriever, es_retriever, query):
            yield one

    async def space_rag(self, session, vector_retriever, es_retriever, query: str, tags: Any = None) \
            -> AsyncIterator[ChatResponse]:
        llm, space_conf = await self.get_space_llm_config()

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

        async for one in llm.astream(inputs):
            yield ChatResponse(
                category=MessageCategory.STREAM,
                message={
                    "content": one.content,
                    "reasoning_content": one.additional_kwargs.get("reasoning_content", ""),
                },
                type="stream"
            )
            reasoning_content += one.additional_kwargs.get("reasoning_content", "")
            answer += one.content
        question_message = await ChatMessageDao.ainsert_one(ChatMessage(
            category=MessageCategory.QUESTION,
            message=json.dumps({
                "query": query,
                "tags": tags,
            }, ensure_ascii=False),
            chat_id=session.chat_id,
            flow_id=session.flow_id,
            user_id=self.login_user.user_id,
            type="end",
            is_bot=False,
        ))
        answer_message = await ChatMessageDao.ainsert_one(ChatMessage(
            category=MessageCategory.ANSWER,
            message=json.dumps({
                "content": answer,
                "reasoning_content": reasoning_content,
            }, ensure_ascii=False),
            chat_id=session.chat_id,
            flow_id=session.flow_id,
            user_id=self.login_user.user_id,
            type="end",
            is_bot=True,
        ))
        logger.info(
            "saved knowledge space messages question_id={} answer_id={}",
            question_message.id,
            answer_message.id,
        )
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

        flow_id = self.generate_flow_id_for_folder(space_id, folder_id)

        session = await MessageSessionDao.afilter_session(flow_ids=[flow_id],
                                                          flow_type=[FlowType.KNOLEDGE_SPACE.value],
                                                          user_ids=[self.login_user.user_id],
                                                          include_delete=False)
        return session

    async def create_chat_folder_session(self, space_id: int, folder_id: int) -> MessageSession:
        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space:
            raise NotFoundError(msg="Knowledge space not found for chat")
        flow_name = space.name
        if folder_id:
            folder_record = await KnowledgeFileDao.query_by_id(folder_id)
            if not folder_record or folder_record.knowledge_id != space_id:
                raise NotFoundError(msg="Knowledge folder not found for chat")
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
        flow_id = self.generate_flow_id_for_folder(space_id, folder_id)
        return await ChatSessionService.get_chat_history(chat_id, flow_id, page_size=page_size)

    async def delete_chat_folder_history(self, space_id: int, folder_id: int, chat_id: str) -> bool:
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

    async def chat_folder(self, knowledge_id: int, folder_id: int, chat_id: str, query: str,
                          tags: Optional[List[Dict]] = None) -> AsyncIterator[ChatResponse]:
        """ Folder RAG query """
        flow_id = self.generate_flow_id_for_folder(knowledge_id, folder_id)
        session = await MessageSessionDao.afilter_session(chat_ids=[chat_id],
                                                          flow_ids=[flow_id],
                                                          user_ids=[self.login_user.user_id],
                                                          include_delete=False)
        if not session:
            raise NotFoundError(msg="Folder session not found")
        session = session[0]

        space = await KnowledgeDao.aquery_by_id(knowledge_id)
        if not space:
            raise NotFoundError(msg="Knowledge space not found for chat")

        vector_retriever, es_retriever = None, None
        if not folder_id:
            milvus_vector = await KnowledgeRag.init_knowledge_milvus_vectorstore(self.login_user.user_id,
                                                                                 knowledge=space)
            es_vector = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=space)
            vector_retriever = milvus_vector.as_retriever(search_kwargs={
                "k": 100,
                "param": {"ef": 110}
            })
            es_retriever = es_vector.as_retriever(search_kwargs={"k": 100})
        else:
            file_record = await KnowledgeFileDao.query_by_id(folder_id)
            if not file_record or file_record.knowledge_id != knowledge_id or file_record.file_type != 0:
                raise NotFoundError(msg="Invalid folder for chat")
            file_level_path = file_record.file_level_path + f"/{file_record.id}"

            file_ids = await SpaceFileDao.get_children_by_prefix(space.id, file_level_path)
            file_ids = [one.id for one in file_ids]
            if tags:
                tag_file_ids = await TagDao.aget_resources_by_tags([one.get("id") for one in tags],
                                                                   resource_type=ResourceTypeEnum.SPACE_FILE)
                tag_file_ids = [int(one.resource_id) for one in tag_file_ids]
                file_ids = list(set(file_ids) & set(tag_file_ids))
            if file_ids:
                milvus_vector = await KnowledgeRag.init_knowledge_milvus_vectorstore(self.login_user.user_id,
                                                                                     knowledge=space)
                vector_retriever = milvus_vector.as_retriever(search_kwargs={
                    "k": 100,
                    "param": {"ef": 110},
                    "expr": f"document_id in {file_ids}"
                })
                es_vector = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=space)
                es_retriever = es_vector.as_retriever(search_kwargs={
                    "k": 100,
                    "filter": [{"terms": {"metadata.document_id": file_ids}}]
                })

        # executeQuery(vector_retriever, es_retriever, query)
        async for one in self.space_rag(session, vector_retriever, es_retriever, query, tags):
            yield one

    async def get_space_llm_config(self) -> Tuple[BaseChatModel, KnowledgeSpaceConfig]:
        """
        Get chat configuration (model and prompts)

        Returns:
            tuple: (model_id, subscription_config)

        Raises: ，
            KnowledgeSpaceLLMNotConfiguredError: If knowledge_space_llm not configured
        """
        # Get workbench LLM configuration
        workbench_llm: WorkbenchModelConfig = await LLMService.get_workbench_llm()

        if not workbench_llm or not workbench_llm.knowledge_space_llm:
            raise KnowledgeSpaceLLMNotConfiguredError()

        model_id = int(workbench_llm.knowledge_space_llm.id)

        llm = await LLMService.get_bisheng_llm(model_id=model_id,
                                               app_id=ApplicationTypeEnum.KNOWLEDGE_SPACE.value,
                                               app_name=ApplicationTypeEnum.KNOWLEDGE_SPACE.value,
                                               app_type=ApplicationTypeEnum.KNOWLEDGE_SPACE,
                                               user_id=self.login_user.user_id)

        # Get subscription configuration
        config = await WorkStationService.get_knowledge_space_config()

        return llm, config

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
