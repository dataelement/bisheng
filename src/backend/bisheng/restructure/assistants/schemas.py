from pydantic import BaseModel


class ChatInput(BaseModel):
    assistant_id: str
    message: str
    chat_id: str = None
    user_id: str = None


class StreamMsg(BaseModel):
    event: str
    data: str = ""

    def __str__(self) -> str:
        return f'event: {self.event}\ndata: {self.data}\n\n'
