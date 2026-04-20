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
from typing import List

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from sse_starlette import EventSourceResponse

from bisheng.api.services.workstation import (
    WorkstationConversation, WorkstationMessage
)
from bisheng.api.v1.schemas import resp_200, ChatResponse
from bisheng.channel.domain.schemas.channel_chat_schema import ChannelArticleChatRequest
from bisheng.channel.domain.services.article_es_service import ArticleEsService
from bisheng.channel.domain.services.channel_chat_service import ChannelChatService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.channel import ChannelChatConversationNotFoundError
from bisheng.common.errcode.http_error import ServerError, UnAuthorizedError
from bisheng.common.schemas.api import resp_500, SSEResponse
from bisheng.database.constants import MessageCategory
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/chat', tags=['Channel Article Chat'])


def custom_json_serializer(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f'Type {type(obj)} not serializable')


def user_message(msgId, conversationId, sender, text):
    msg = json.dumps({
        'message': {
            'messageId': msgId,
            'conversationId': conversationId,
            'sender': sender,
            'text': text
        },
        'created': True
    })
    return f'event: message\ndata: {msg}\n\n'


def step_message(stepId, runId, index, msgId):
    msg = json.dumps({
        'event': 'on_run_step',
        'data': {
            'id': stepId,
            'runId': runId,
            'type': 'message_creation',
            'index': index,
            'stepDetails': {
                'type': 'message_creation',
                'message_creation': {
                    'message_id': msgId
                }
            }
        }
    })
    return f'event: message\ndata: {msg}\n\n'


def delta(id, delta):
    return {'id': id, 'delta': delta}


async def final_message(conversation: MessageSession, title: str, requestMessage: ChatMessage,
                        text: str, error: bool, modelName: str,
                        source_document: List[Document] = None):
    responseMessage = await ChatMessageDao.ainsert_one(
        ChatMessage(
            user_id=conversation.user_id,
            chat_id=conversation.chat_id,
            flow_id=conversation.flow_id,
            type='assistant',
            is_bot=True,
            message=text,
            category='answer',
            sender=modelName,
            extra=json.dumps({
                'parentMessageId': requestMessage.id,
                'error': error
            }),
            source=0
        ))

    msg = json.dumps(
        {
            'final': True,
            'conversation': WorkstationConversation.from_chat_session(conversation).model_dump(),
            'title': title,
            'requestMessage': (await WorkstationMessage.from_chat_message(requestMessage)).model_dump(),
            'responseMessage': (await WorkstationMessage.from_chat_message(responseMessage)).model_dump(),
        },
        default=custom_json_serializer)
    return f'event: message\ndata: {msg}\n\n'


@router.post('/completions', summary='Channel Article AI Assistant Chat')
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
        logger.exception(f'Error in channel article chat setup: {e}')
        return EventSourceResponse(iter([ServerError(exception=e).to_sse_event_instance()]))

    async def event_stream():

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
                else (
                    "# 参考资料\n```\n{article_content}\n```\n# 用户问题\n{question}"
                )
            )
            user_prompt = user_prompt_template.format(
                article_content=article_content,
                question=data.text
            )
            await ChatMessageDao.ainsert_one(
                ChatMessage(
                    user_id=login_user.user_id,
                    chat_id=conversation.chat_id,
                    flow_id=data.article_doc_id,
                    type='human',
                    is_bot=False,
                    sender='User',
                    message=json.dumps({"query": data.text}, ensure_ascii=False),
                    category=MessageCategory.QUESTION,
                    source=0,
                ))
            # Get chat history (excluding the latest one)
            history_messages = (await ChannelChatService.get_chat_history(conversationId, 8))[:-1]

            # Build LLM input
            inputs = [
                SystemMessage(content=system_prompt),
                *history_messages,
                HumanMessage(content=user_prompt)
            ]

            answer = ""
            reasoning_answer = ""
            # Streaming call to LLM
            async for chunk in bishengllm.astream(inputs):
                content = chunk.content
                reasoning_content = chunk.additional_kwargs.get('reasoning_content', '')
                answer += content
                reasoning_answer += reasoning_content
                yield SSEResponse(data=ChatResponse(
                    category=MessageCategory.STREAM,
                    message={
                        "content": content,
                        "reasoning_content": reasoning_content,
                    },
                    type="stream"
                )).to_string()

            yield SSEResponse(data=ChatResponse(
                category=MessageCategory.STREAM,
                message={
                    "content": answer,
                    "reasoning_content": reasoning_answer
                },
                type="end"
            )).to_string()

            # Append reasoning process to final result
            await ChatMessageDao.ainsert_one(
                ChatMessage(
                    category=MessageCategory.ANSWER,
                    message=json.dumps({
                        "content": answer,
                        "reasoning_content": reasoning_answer
                    }, ensure_ascii=False),
                    user_id=login_user.user_id,
                    chat_id=conversation.chat_id,
                    flow_id=data.article_doc_id,
                    type="end",
                    is_bot=True,
                )
            )
        except BaseErrorCode as e:
            yield e.to_sse_event_instance_str()
        except Exception as e:
            logger.exception(f'Error in channel article chat processing')
            yield ServerError(exception=e).to_sse_event_instance_str()

    try:
        return StreamingResponse(event_stream(), media_type='text/event-stream')
    except Exception as e:
        logger.exception(f'Error creating channel article chat stream: {e}')
        return EventSourceResponse(iter([ServerError(exception=e).to_sse_event_instance()]))


@router.get('/messages/{article_doc_id}', summary='Query Channel Article AI Assistant Chat History')
async def get_chat_history(
        article_doc_id: str,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Query Channel Article AI Assistant Chat History Content"""
    messages = await ChannelChatService.get_chat_messages(article_doc_id, login_user)
    if messages is None:
        return UnAuthorizedError.return_resp()
    return resp_200(data=messages)


@router.delete('/messages/{article_doc_id}', summary='Clear Channel Article AI Assistant Chat Content')
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
