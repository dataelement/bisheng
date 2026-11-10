"""Bounded desktop rating updates. The conversation log itself is not part of this contract."""

from typing import Literal

from pydantic import Field, model_validator

from bisheng.dsh.domain.schemas.contracts import DshContract

FeedbackRating = Literal["positive", "negative"]
FeedbackCategory = Literal[
    "task-result",
    "instruction-following",
    "product-interaction",
    "service-stability",
    "resource-cost",
    "security-privacy-permission",
    "other",
]


def _plain(value: str, *, allow_blank: bool) -> bool:
    if any((ord(char) < 32 and char not in "\t\n\r") or ord(char) == 127 for char in value):
        return False
    return allow_blank or bool(value.strip())


class AuditMessageFeedbackUpdate(DshContract):
    conversation_id: str = Field(min_length=1, max_length=256)
    message_id: str = Field(min_length=1, max_length=256)
    event_seq: int = Field(ge=0, le=9007199254740991)
    op: Literal["put", "delete"]
    rating: FeedbackRating | None = None
    category: FeedbackCategory | None = None
    note: str | None = None

    @model_validator(mode="after")
    def valid_feedback(self):
        if not _plain(self.conversation_id, allow_blank=False) or not _plain(self.message_id, allow_blank=False):
            raise ValueError("Invalid feedback identity")
        if self.op == "delete":
            if self.rating is not None or self.category is not None or self.note is not None:
                raise ValueError("Delete carries no rating")
            return self
        if self.rating is None:
            raise ValueError("Rating is required")
        if self.note is not None and (
            not _plain(self.note, allow_blank=False) or len(self.note.encode("utf-8")) > 8192
        ):
            raise ValueError("Invalid feedback note")
        return self
