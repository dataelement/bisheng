from pydantic import BaseModel, Field, field_validator


class LikeMessageInput(BaseModel):
    message_id: int = Field(gt=0)
    liked: int = Field(ge=0, le=2, strict=True)


class CommentMessageInput(BaseModel):
    message_id: int = Field(gt=0)
    comment: str = Field(min_length=1, max_length=4096)

    @field_validator("comment")
    @classmethod
    def validate_comment(cls, value: str) -> str:
        value = value.strip()
        if not value or value in {"break_answer", "inaction"}:
            raise ValueError("请输入有效反馈内容")
        return value
