"""
频道文章AI助手对话 API 端点

提供以下功能：
- POST /chat/completions: SSE流式对话
- GET /chat/messages/{conversationId}: 查询对话历史
- DELETE /chat/messages/{conversationId}: 清空对话内容
"""
import json
import logging
from datetime import datetime
from typing import List
from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from sse_starlette import EventSourceResponse

from bisheng.api.services.workstation import (
    WorkStationService, WorkstationConversation, WorkstationMessage
)
from bisheng.api.v1.schemas import resp_200, UnifiedResponseModel
from bisheng.channel.domain.schemas.channel_chat_schema import ChannelArticleChatRequest
from bisheng.channel.domain.services.article_es_service import ArticleEsService
from bisheng.channel.domain.services.channel_chat_service import ChannelChatService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.channel import ArticleNotFoundError, ChannelChatConversationNotFoundError
from bisheng.common.errcode.http_error import ServerError, UnAuthorizedError
from bisheng.common.schemas.api import resp_500
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


class SSEResponse:
    def __init__(self, event: str, data: dict):
        self.event = event
        self.data = data

    def toString(self):
        return f'event: {self.event}\ndata: {json.dumps(self.data)}\n\n'


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


@router.post('/completions', summary='频道文章AI助手对话')
async def chat_completions(
        data: ChannelArticleChatRequest,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """
    频道文章AI助手对话接口，SSE流式返回。
    根据文章ID获取文章内容作为对话上下文，与LLM进行多轮对话。
    """
    try:
        # 1. 获取文章内容
        article_es_service = ArticleEsService()
        article = await ChannelChatService.get_article_content(article_es_service, data.article_doc_id)
        article_title = article.title
        article_content = article.content

        # 2. 初始化会话
        conversation, message, bishengllm, is_new_conv = await ChannelChatService.initialize_chat(
            data, login_user, article_title
        )
        conversationId = conversation.chat_id

    except (BaseErrorCode, ValueError) as e:
        error_response = e if isinstance(e, BaseErrorCode) else ServerError(msg=str(e))
        return EventSourceResponse(iter([error_response.to_sse_event_instance()]))
    except Exception as e:
        logger.exception(f'Error in channel article chat setup: {e}')
        return EventSourceResponse(iter([ServerError(exception=e).to_sse_event_instance()]))

    async def event_stream():
        yield user_message(message.id, conversationId, 'User', data.text)

        error = False
        final_res = ''
        reasoning_res = ''
        runId = uuid4().hex
        index = 0
        stepId = None
        model_name = data.model

        try:
            # 构建文章上下文提示
            prompt = ChannelChatService.build_article_context_prompt(
                title=article_title,
                content=article_content,
                question=data.text
            )

            # 保存 prompt 到消息的 extra 字段
            extra = json.loads(message.extra) if message.extra else {}
            extra['prompt'] = prompt
            message.extra = json.dumps(extra, ensure_ascii=False)
            await ChatMessageDao.ainsert_one(message)

            # 获取对话历史（排除最新一条）
            history_messages = (await ChannelChatService.get_chat_history(conversationId, 8))[:-1]

            # 构建 LLM 输入
            system_prompt = (
                f"你是一个专业的AI助手，正在帮助用户分析和讨论一篇文章。"
                f"以下是文章信息：\n\n"
                f"## 文章标题\n{article_title}\n\n"
                f"## 文章内容\n{article_content}\n\n"
                f"请基于这篇文章的内容来回答用户的问题。当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            inputs = [SystemMessage(content=system_prompt), *history_messages, HumanMessage(content=data.text)]

            stepId = 'step_' + uuid4().hex
            yield step_message(stepId, runId, index, f'msg_{uuid4().hex}')
            index += 1

            # 流式调用 LLM
            async for chunk in bishengllm.astream(inputs):
                content = chunk.content
                reasoning_content = chunk.additional_kwargs.get('reasoning_content', '')

                if content:
                    final_res += content
                    yield SSEResponse(event='on_message_delta',
                                      data=delta(id=stepId,
                                                 delta={'content': [{'type': 'text', 'text': content}]})).toString()
                if reasoning_content:
                    reasoning_res += reasoning_content
                    yield SSEResponse(event='on_reasoning_delta',
                                      data=delta(id=stepId, delta={
                                          'content': [{'type': 'think', 'think': reasoning_content}]})).toString()

            # 拼接思考过程到最终结果
            if reasoning_res:
                final_res = ':::thinking\n' + reasoning_res + '\n:::' + final_res

        except BaseErrorCode as e:
            error = True
            final_res = json.dumps(e.to_dict())
            yield e.to_sse_event_instance_str()
        except Exception as e:
            error = True
            server_error = ServerError(exception=e)
            logger.exception(f'Error in channel article chat processing')
            final_res = json.dumps(server_error.to_dict())
            yield server_error.to_sse_event_instance_str()

        # 发送最终消息
        yield await final_message(conversation, conversation.flow_name, message, final_res,
                                  error, model_name)

    try:
        return StreamingResponse(event_stream(), media_type='text/event-stream')
    except Exception as e:
        logger.exception(f'Error creating channel article chat stream: {e}')
        return EventSourceResponse(iter([ServerError(exception=e).to_sse_event_instance()]))


@router.get('/messages/{conversationId}', summary='查询频道文章AI助手对话历史')
async def get_chat_history(
        conversationId: str,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """查询频道文章AI助手对话历史内容"""
    messages = await ChannelChatService.get_chat_messages(conversationId, login_user)
    if messages is None:
        return UnAuthorizedError.return_resp()
    return resp_200(data=messages)


@router.delete('/messages/{conversationId}', summary='清空频道文章AI助手对话内容')
async def clear_chat(
        conversationId: str,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """清空频道文章AI助手对话内容"""
    try:
        result = await ChannelChatService.clear_chat(conversationId, login_user)
        if not result:
            return UnAuthorizedError.return_resp()
        return resp_200(data=True)
    except ChannelChatConversationNotFoundError as e:
        return resp_500(message=e.Msg)
    except Exception as e:
        logger.error(f"Failed to clear channel article chat: {e}")
        return resp_500(message="Failed to clear chat")
