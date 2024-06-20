from uuid import uuid4
from bisheng.database.models.assistant import AssistantDao, AssistantStatus
from bisheng.restructure.assistants.agent import RtcAssistantAgent
from bisheng.restructure.assistants.schemas import StreamMsg, ChatInput
from bisheng.restructure.assistants.services import MsgCategory, MsgFrom, chat_by_agent, get_chat_history, \
    record_message
from bisheng.restructure.logger import log_trace
from bisheng.utils.logger import logger
from fastapi import APIRouter
from fastapi.responses import ORJSONResponse, StreamingResponse

router = APIRouter(prefix='/assistant')


@router.post('/sse', status_code=200, response_class=StreamingResponse)
@log_trace
async def chat(chat_input: ChatInput):
    message = chat_input.message
    user_id = chat_input.user_id

    async def _event_stream():
        if chat_id := chat_input.chat_id:
            chat_history = get_chat_history(chat_id)
        else:
            chat_history = []
            chat_id = uuid4().hex
            yield str(StreamMsg(event='chat', data=chat_id))
        assistant = AssistantDao.get_one_assistant(chat_input.assistant_id)
        if not assistant:
            yield str(StreamMsg(event='error', data="该助手已被删除"))
            return
        if assistant.status != AssistantStatus.ONLINE.value:
            yield str(StreamMsg(event='error', data="当前助手未上线，无法直接对话"))
            return
        record_message(chat_id, user_id, MsgFrom.Human, message, MsgCategory.Question)
        gpt_agent = await RtcAssistantAgent.create(assistant)
        answer = await chat_by_agent(gpt_agent, message, chat_history)
        record_message(chat_id, user_id, MsgFrom.Bot, answer, MsgCategory.Answer)
        yield str(StreamMsg(event='message', data=answer))

    try:
        return StreamingResponse(_event_stream(), media_type='text/event-stream')
    except Exception as exc:
        logger.error(exc)
        return ORJSONResponse(status_code=500, content=str(exc))
