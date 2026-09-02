"""
Channel Article AI Assistant Chat API Endpoints

Provides the following functionalities:
- POST /chat/completions: SSE streaming chat
- GET /chat/messages/{article_doc_id}: Query chat history
- DELETE /chat/messages/{article_doc_id}: Clear chat content
"""

import json
import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel
from sse_starlette import EventSourceResponse

from bisheng.api.services.workstation import WorkstationConversation, WorkstationMessage
from bisheng.api.v1.schemas import ChatResponse, resp_200
from bisheng.channel.domain.schemas.channel_chat_schema import ChannelArticleChatRequest
from bisheng.channel.domain.services.article_es_service import ArticleEsService
from bisheng.channel.domain.services.channel_chat_service import ChannelChatService
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.channel import ChannelChatConversationNotFoundError
from bisheng.common.errcode.http_error import ServerError, UnAuthorizedError
from bisheng.common.errcode.workstation import LLMRateLimitError
from bisheng.common.schemas.api import SSEResponse, resp_500
from bisheng.database.constants import MessageCategory
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession
from bisheng.llm.domain.services.model_rate_limit import (
    ModelCallContext,
    ModelCallEntry,
    ModelCallResumeMode,
    ModelRateLimitService,
    RecoveryAction,
    RecoveryCommand,
)
from bisheng.llm.domain.services.model_recovery_service import (
    ModelRecoveryService,
    RecoveryNotAllowedError,
    build_recovery_rejected_sse,
)
from bisheng.llm.domain.utils import extract_reasoning_content

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Channel Article Chat"])


class ChannelChatRecoveryRequest(BaseModel):
    attempt_id: str
    subject_id: str
    action: RecoveryAction
    target_model_id: int | None = None


class ChannelChatRecoveryPort:
    def __init__(self, login_user: UserPayload) -> None:
        self.login_user = login_user
        self.question: ChatMessage | None = None
        self.article = None

    async def ensure_subject_access(self, execution) -> None:
        try:
            message = await ChatMessageDao.aget_message_by_id(int(execution.subject_id))
        except (TypeError, ValueError) as exc:
            raise RecoveryNotAllowedError("channel execution subject is invalid") from exc
        if message is None or message.user_id != self.login_user.user_id:
            raise RecoveryNotAllowedError("channel execution subject is unavailable")
        try:
            extra = json.loads(message.extra or "{}")
            recovery = extra["recovery_request"]
            if str(message.id) != execution.execution_id:
                raise RecoveryNotAllowedError("channel recovery identity does not match")
            execution.active_model_id = int(recovery["model_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RecoveryNotAllowedError("channel recovery metadata is unavailable") from exc
        article = await ChannelChatService.get_article_content(ArticleEsService(), message.flow_id)
        await ChannelService.ensure_article_sensitive_view_allowed(article, self.login_user)
        self.question = message
        self.article = article

    async def ensure_target_model(self, execution, model_id: int, *, allow_busy: bool = False) -> None:
        if not allow_busy:
            states = await ModelRateLimitService().list_model_states(self.login_user.tenant_id, [model_id])
            if states[model_id].rate_limit_state.value != "normal":
                raise RecoveryNotAllowedError("target model is rate limited")


def custom_json_serializer(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def user_message(msgId, conversationId, sender, text):
    msg = json.dumps(
        {
            "message": {"messageId": msgId, "conversationId": conversationId, "sender": sender, "text": text},
            "created": True,
        }
    )
    return f"event: message\ndata: {msg}\n\n"


def step_message(stepId, runId, index, msgId):
    msg = json.dumps(
        {
            "event": "on_run_step",
            "data": {
                "id": stepId,
                "runId": runId,
                "type": "message_creation",
                "index": index,
                "stepDetails": {"type": "message_creation", "message_creation": {"message_id": msgId}},
            },
        }
    )
    return f"event: message\ndata: {msg}\n\n"


def delta(id, delta):
    return {"id": id, "delta": delta}


async def final_message(
    conversation: MessageSession,
    title: str,
    requestMessage: ChatMessage,
    text: str,
    error: bool,
    modelName: str,
    source_document: list[Document] = None,
):
    responseMessage = await ChatMessageDao.ainsert_one(
        ChatMessage(
            user_id=conversation.user_id,
            chat_id=conversation.chat_id,
            flow_id=conversation.flow_id,
            type="assistant",
            is_bot=True,
            message=text,
            category="answer",
            sender=modelName,
            extra=json.dumps({"parentMessageId": requestMessage.id, "error": error}),
            source=0,
        )
    )

    msg = json.dumps(
        {
            "final": True,
            "conversation": WorkstationConversation.from_chat_session(conversation).model_dump(),
            "title": title,
            "requestMessage": (await WorkstationMessage.from_chat_message(requestMessage)).model_dump(),
            "responseMessage": (await WorkstationMessage.from_chat_message(responseMessage)).model_dump(),
        },
        default=custom_json_serializer,
    )
    return f"event: message\ndata: {msg}\n\n"


@router.post("/completions", summary="Channel Article AI Assistant Chat")
async def chat_completions(
    data: ChannelArticleChatRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """
    Channel Article AI Assistant Chat API, returns SSE stream.
    Fetches article content by article ID as conversation context, conducts multi-turn conversation with LLM.
    """
    try:
        # 1. Fetch article content
        article_es_service = ArticleEsService()
        article = await ChannelChatService.get_article_content(article_es_service, data.article_doc_id)
        await ChannelService.ensure_article_sensitive_view_allowed(article, login_user)
        article_title = article.title
        article_content = article.content

        # 2. Initialize session and get configuration
        conversation, bishengllm, is_new_conv, subscription_config = await ChannelChatService.initialize_chat(
            data, login_user, article_title
        )
        conversationId = conversation.chat_id

        # 3. Truncate article content if needed
        max_chunk_size = subscription_config.max_chunk_size if subscription_config else 15000
        article_content = ChannelChatService._truncate_article_content(article_content, max_chunk_size)

    except (BaseErrorCode, ValueError) as e:
        error_response = e if isinstance(e, BaseErrorCode) else ServerError(msg=str(e))
        return EventSourceResponse(iter([error_response.to_sse_event_instance()]))
    except Exception as e:
        logger.exception(f"Error in channel article chat setup: {e}")
        return EventSourceResponse(iter([ServerError(exception=e).to_sse_event_instance()]))

    async def event_stream():
        attempt_id = str(uuid4())
        call_context = None
        answer = ""
        reasoning_answer = ""
        try:
            # Build system prompt from config or default
            system_prompt = (
                subscription_config.system_prompt
                if subscription_config and subscription_config.system_prompt
                else "You are a professional AI assistant helping users analyze and discuss articles."
            )

            # Build user prompt from template or default
            user_prompt_template = (
                subscription_config.user_prompt
                if subscription_config and subscription_config.user_prompt
                else ("# 参考资料\n```\n{article_content}\n```\n# 用户问题\n{question}")
            )
            user_prompt = user_prompt_template.format(article_content=article_content, question=data.text)
            question_message = await ChatMessageDao.ainsert_one(
                ChatMessage(
                    user_id=login_user.user_id,
                    chat_id=conversation.chat_id,
                    flow_id=data.article_doc_id,
                    type="human",
                    is_bot=False,
                    sender="User",
                    message=json.dumps({"query": data.text}, ensure_ascii=False),
                    extra=json.dumps(
                        {
                            "recovery_request": {
                                "article_doc_id": data.article_doc_id,
                                "model_id": data.model_id,
                            },
                        }
                    ),
                    category=MessageCategory.QUESTION,
                    source=0,
                )
            )
            execution_id = str(question_message.id)
            call_context = ModelCallContext(
                tenant_id=login_user.tenant_id,
                user_id=login_user.user_id,
                model_id=data.model_id,
                entry=ModelCallEntry.CHANNEL,
                execution_id=execution_id,
                attempt_id=attempt_id,
                subject_type="chat_message",
                subject_id=str(question_message.id),
                resume_mode=ModelCallResumeMode.READ_ONLY_REINVOKE,
            )
            rate_limit_service = ModelRateLimitService()
            states = await rate_limit_service.list_model_states(login_user.tenant_id, [data.model_id])
            observed_status_version = states[data.model_id].status_version
            # Get chat history (excluding the latest one)
            history_messages = (await ChannelChatService.get_chat_history(conversationId, 8))[:-1]

            # Build LLM input
            inputs = [SystemMessage(content=system_prompt), *history_messages, HumanMessage(content=user_prompt)]

            # Streaming call to LLM
            async for chunk in bishengllm.astream(inputs):
                content = chunk.content
                reasoning_content = extract_reasoning_content(chunk)
                answer += content
                reasoning_answer += reasoning_content
                yield SSEResponse(
                    data=ChatResponse(
                        category=MessageCategory.STREAM,
                        message={
                            "content": content,
                            "reasoning_content": reasoning_content,
                        },
                        type="stream",
                    )
                ).to_string()

            # Persist the answer BEFORE the end event so we can hand the client the
            # real ChatMessage id. The client renders the streamed answer under a
            # temporary placeholder id; without the real id, like/dislike clicked
            # before a reload writes to a non-existent row and silently vanishes.
            answer_message = await ChatMessageDao.ainsert_one(
                ChatMessage(
                    category=MessageCategory.ANSWER,
                    message=json.dumps({"content": answer, "reasoning_content": reasoning_answer}, ensure_ascii=False),
                    extra="{}",
                    user_id=login_user.user_id,
                    chat_id=conversation.chat_id,
                    flow_id=data.article_doc_id,
                    type="end",
                    is_bot=True,
                )
            )
            await rate_limit_service.observe_call_success(call_context, observed_status_version)

            yield SSEResponse(
                data=ChatResponse(
                    category=MessageCategory.STREAM,
                    message={
                        "content": answer,
                        "reasoning_content": reasoning_answer,
                        "message_id": answer_message.id,
                    },
                    type="end",
                )
            ).to_string()
        except BaseErrorCode as e:
            yield e.to_sse_event_instance_str()
        except Exception as e:
            logger.exception("Error in channel article chat processing")
            observation = (
                await ModelRateLimitService().observe_call_failure(call_context, e)
                if call_context is not None
                else None
            )
            if observation is None:
                yield ServerError(exception=e).to_sse_event_instance_str()
                return
            yield LLMRateLimitError(
                execution_id=execution_id,
                attempt_id=attempt_id,
                error_type="rate_limit",
                rate_limit_state=(
                    observation.rate_limit_state.value if observation.rate_limit_state is not None else None
                ),
                busy_until=observation.busy_until.isoformat() if observation.busy_until else None,
                status_version=observation.status_version,
                recovery_subject_id=observation.subject_id,
                model_id=observation.model_id,
            ).to_sse_event_instance_str()

    try:
        return StreamingResponse(event_stream(), media_type="text/event-stream")
    except Exception as e:
        logger.exception(f"Error creating channel article chat stream: {e}")
        return EventSourceResponse(iter([ServerError(exception=e).to_sse_event_instance()]))


@router.post("/executions/{execution_id}/recover")
async def recover_channel_chat(
    execution_id: str,
    req: ChannelChatRecoveryRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    port = ChannelChatRecoveryPort(login_user)
    recovery_service = ModelRecoveryService()
    command = RecoveryCommand(
        execution_id=execution_id,
        attempt_id=req.attempt_id,
        subject_id=req.subject_id,
        action=req.action,
        target_model_id=req.target_model_id,
    )
    try:
        claimed = await recovery_service.claim_recovery(
            command,
            tenant_id=login_user.tenant_id,
            user_id=login_user.user_id,
            entry=ModelCallEntry.CHANNEL,
            subject_type="chat_message",
            resume_mode=ModelCallResumeMode.READ_ONLY_REINVOKE,
            port=port,
        )
    except BaseErrorCode:
        return StreamingResponse(
            iter([build_recovery_rejected_sse(command)]),
            media_type="text/event-stream",
        )
    if not claimed.should_execute:
        return StreamingResponse(
            iter([build_recovery_rejected_sse(claimed)]),
            media_type="text/event-stream",
        )
    if port.question is None or port.article is None:
        await recovery_service.release_recovery_lock(
            claimed,
            tenant_id=login_user.tenant_id,
            user_id=login_user.user_id,
        )
        return StreamingResponse(
            iter([build_recovery_rejected_sse(command)]),
            media_type="text/event-stream",
        )
    try:
        question_data = json.loads(port.question.message or "{}")
        data = ChannelArticleChatRequest(
            article_doc_id=port.question.flow_id,
            text=str(question_data.get("query", "")),
            modelId=claimed.model_id,
        )
        conversation, llm, _, subscription_config = await ChannelChatService.initialize_chat(
            data,
            login_user,
            port.article.title,
        )
    except BaseErrorCode as exc:
        await recovery_service.release_recovery_lock(
            claimed,
            tenant_id=login_user.tenant_id,
            user_id=login_user.user_id,
        )
        return StreamingResponse(
            iter([exc.to_sse_event_instance_str()]),
            media_type="text/event-stream",
        )
    except Exception as exc:
        logger.exception("Channel chat recovery setup failed")
        await recovery_service.release_recovery_lock(
            claimed,
            tenant_id=login_user.tenant_id,
            user_id=login_user.user_id,
        )
        return StreamingResponse(
            iter([ServerError(exception=exc).to_sse_event_instance_str()]),
            media_type="text/event-stream",
        )

    async def event_stream():
        answer = ""
        reasoning = ""
        context = ModelCallContext(
            tenant_id=login_user.tenant_id,
            user_id=login_user.user_id,
            model_id=claimed.model_id,
            entry=ModelCallEntry.CHANNEL,
            execution_id=claimed.execution_id,
            attempt_id=claimed.attempt_id,
            subject_type="chat_message",
            subject_id=str(port.question.id),
            resume_mode=ModelCallResumeMode.READ_ONLY_REINVOKE,
            action=claimed.action,
        )
        limiter = ModelRateLimitService()
        states = await limiter.list_model_states(login_user.tenant_id, [claimed.model_id])
        observed_version = states[claimed.model_id].status_version
        try:
            max_chunk = subscription_config.max_chunk_size if subscription_config else 15000
            article_content = ChannelChatService._truncate_article_content(port.article.content, max_chunk)
            system_prompt = (
                subscription_config.system_prompt
                if subscription_config and subscription_config.system_prompt
                else "You are a professional AI assistant helping users analyze and discuss articles."
            )
            user_template = (
                subscription_config.user_prompt
                if subscription_config and subscription_config.user_prompt
                else "# 参考资料\n```\n{article_content}\n```\n# 用户问题\n{question}"
            )
            user_prompt = user_template.format(article_content=article_content, question=data.text)
            history = (await ChannelChatService.get_chat_history(conversation.chat_id, 8))[:-1]
            inputs = [SystemMessage(content=system_prompt), *history, HumanMessage(content=user_prompt)]
            async for chunk in llm.astream(inputs):
                content = chunk.content
                chunk_reasoning = extract_reasoning_content(chunk)
                answer += content
                reasoning += chunk_reasoning
                yield SSEResponse(
                    data=ChatResponse(
                        category=MessageCategory.STREAM,
                        message={"content": content, "reasoning_content": chunk_reasoning},
                        type="stream",
                    )
                ).to_string()
        except Exception as exc:
            logger.exception("Channel chat recovery failed")
            observation = await limiter.observe_call_failure(context, exc)
            if observation is None:
                yield ServerError(exception=exc).to_sse_event_instance_str()
                return
            yield LLMRateLimitError(
                execution_id=context.execution_id,
                attempt_id=context.attempt_id,
                error_type="rate_limit",
                rate_limit_state=(observation.rate_limit_state.value if observation.rate_limit_state else None),
                busy_until=observation.busy_until.isoformat() if observation.busy_until else None,
                status_version=observation.status_version,
                recovery_subject_id=observation.subject_id,
                model_id=observation.model_id,
            ).to_sse_event_instance_str()
            return
        answer_message = await _persist_channel_answer(
            conversation,
            data,
            answer,
            reasoning,
        )
        await limiter.observe_call_success(context, observed_version)
        yield SSEResponse(
            data=ChatResponse(
                category=MessageCategory.STREAM,
                message={"content": answer, "reasoning_content": reasoning, "message_id": answer_message.id},
                type="end",
            )
        ).to_string()

    return StreamingResponse(
        recovery_service.release_lock_after_stream(
            event_stream(),
            claimed,
            tenant_id=login_user.tenant_id,
            user_id=login_user.user_id,
        ),
        media_type="text/event-stream",
    )


async def _persist_channel_answer(
    conversation,
    data,
    answer,
    reasoning,
):
    return await ChatMessageDao.ainsert_one(
        ChatMessage(
            category=MessageCategory.ANSWER,
            message=json.dumps({"content": answer, "reasoning_content": reasoning}, ensure_ascii=False),
            extra="{}",
            user_id=conversation.user_id,
            chat_id=conversation.chat_id,
            flow_id=data.article_doc_id,
            type="end",
            is_bot=True,
        )
    )


@router.get("/messages/{article_doc_id}", summary="Query Channel Article AI Assistant Chat History")
async def get_chat_history(
    article_doc_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Query Channel Article AI Assistant Chat History Content"""
    messages = await ChannelChatService.get_chat_messages(article_doc_id, login_user)
    if messages is None:
        return UnAuthorizedError.return_resp()
    return resp_200(data=messages)


@router.delete("/messages/{article_doc_id}", summary="Clear Channel Article AI Assistant Chat Content")
async def clear_chat(
    article_doc_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Clear Channel Article AI Assistant Chat Content"""
    try:
        await ChannelChatService.clear_chat(article_doc_id, login_user)
        return resp_200(data=True)
    except ChannelChatConversationNotFoundError as e:
        return resp_500(message=e.Msg)
    except Exception as e:
        logger.error(f"Failed to clear channel article chat: {e}")
        return resp_500(message="Failed to clear chat")
