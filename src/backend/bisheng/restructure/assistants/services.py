from langchain_core.messages import AIMessage, HumanMessage

from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.restructure.assistants.agent import RtcAssistantAgent
from bisheng.settings import settings
from bisheng.utils.logger import logger

DEFAULT_SIZE = 20


class MsgCategory:
    Question = 'question'
    Answer = 'answer'


class MsgFrom:
    Human = 1
    Bot = 2


def get_chat_history(chat_id: str, size: int = DEFAULT_SIZE):
    chat_history = []
    messages = ChatMessageDao.get_messages_by_chat_id(chat_id, ['question', 'answer'], size)
    for one in messages:
        # bug fix When constructing multi-turn dialogues, the input and response of
        # the user and the assistant were reversed, leading to incorrect question-and-answer sequences.
        if one.category == MsgCategory.Question:
            chat_history.append(HumanMessage(content=one.message))
        elif one.category == MsgCategory.Answer:
            chat_history.append(AIMessage(content=one.message))
    logger.info(f"loaded {len(chat_history)} chat history for chat_id {chat_id}")
    return chat_history


async def chat_by_agent(agent: RtcAssistantAgent, message: str, chat_history: list):
    new_message = HumanMessage(content=message)
    if chat_history:
        chat_history.append(new_message)
        inputs = chat_history
    else:
        inputs = [new_message]
    logger.info(f"start calling langchain agent...")
    answer = await agent.run_agent(inputs)
    # todo: 后续优化代码解释器的实现方案，保证输出的文件可以公开访问
    # 获取minio的share地址，把share域名去掉, 为毕昇的部署方案特殊处理下
    if gpts_tool_conf := settings.get_from_db('gpts').get('tools'):
        if bisheng_code_conf := gpts_tool_conf.get("bisheng_code_interpreter"):
            answer = answer.replace(f"http://{bisheng_code_conf['minio']['MINIO_SHAREPOIN']}", "")
    return answer


def record_message(chat_id: str, user_id: str, msg_from: str, message: str, category: str):
    return ChatMessageDao.insert_one(ChatMessage(
        is_bot=msg_from == MsgFrom.Bot,
        source=False,
        message=message,
        category=category,
        type=msg_from,
        flow_id=chat_id,  # todo 智能体不是单独的flow
        chat_id=chat_id,
        user_id=user_id,
    ))
