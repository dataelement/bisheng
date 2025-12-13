from pydantic import BaseModel


class SyncMessage(BaseModel):
    is_send: bool
    message: str
    create_time: str
    extra: dict
