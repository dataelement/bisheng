from bisheng.api.v1.schemas import ChatMessage
from bisheng.database.base import session_getter


def comment_answer(message_id: int, comment: str):
    with session_getter() as session:
        message = session.get(ChatMessage, message_id)
        if message:
            message.remark = comment[:4096]
            session.add(message)
            session.commit()
