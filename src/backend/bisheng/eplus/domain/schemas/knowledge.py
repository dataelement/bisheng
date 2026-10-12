"""Robot-only retrieval inputs and authoritative file provenance."""

from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator


@dataclass(frozen=True)
class RobotFileSource:
    file_id: int
    file_name: str
    space_id: int
    space_name: str


class RobotKnowledgeInput(BaseModel):
    query: str = Field(description="需要检索或核实的问题。")
    file_name: str | None = Field(
        default=None,
        max_length=500,
        description="用户明确指定的完整文件名, 包含扩展名, 按原样传入; 未指定具体文件时不传, 不猜测文件名。",
    )

    @field_validator("file_name")
    @classmethod
    def reject_blank_name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("file_name must not be blank")
        return value
