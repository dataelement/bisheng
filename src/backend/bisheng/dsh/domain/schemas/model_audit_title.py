"""Strict bounded title updates; never model parameters or trusted identity."""

from pydantic import Field, field_validator

from bisheng.dsh.domain.schemas.contracts import DshContract


class AuditTitleUpdate(DshContract):
    conversation_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=512)
    title_event_seq: int = Field(ge=0, le=9007199254740991)

    @field_validator("conversation_id", "title")
    @classmethod
    def valid_text(cls, value, info):
        encoded = value.encode("utf8")
        if info.field_name == "title" and (
            not value.strip() or len(encoded) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("Invalid title text")
        return value
