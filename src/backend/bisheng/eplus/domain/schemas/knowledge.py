"""Robot-only retrieval inputs and authoritative file provenance."""

from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator, model_validator


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
    file_name_query: str | None = Field(
        default=None,
        max_length=200,
        description="按主题查找文件时可传文件名关键词, 例如'深圳市 医学研究'; 多词用空格分隔且全部匹配。只提取主题, 不传'有哪些文件'等问句。它补充文件名匹配但不限制全空间正文检索; 同一次调用也返回相关正文。",
    )

    @field_validator("file_name", "file_name_query")
    @classmethod
    def reject_blank_name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("file_name must not be blank")
        return value

    @model_validator(mode="after")
    def exclusive_filename_lookup(self):
        if self.file_name is not None and self.file_name_query is not None:
            raise ValueError("use either an exact filename or filename keywords")
        return self
