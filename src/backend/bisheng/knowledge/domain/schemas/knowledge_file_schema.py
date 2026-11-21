from typing import Any

from pydantic import Field

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileRead


class KnowledgeFileInfoRes(KnowledgeFileRead):
    """Knowledge Base File Information Response Body"""

    creat_user: str | None = Field(default=None, description="Create user name")
    update_user: str | None = Field(default=None, description="Update user name")
    # `status` is the outcome of the LATEST processing attempt; content in the
    # index is the LAST SUCCESSFUL one. These fields carry the missing half so a
    # client never presents retained content as this attempt's result.
    version_id: int | None = Field(default=None, description="Version row owning this physical file")
    version_no: int | None = Field(default=None, description="Version number inside its document")
    is_primary_version: bool | None = Field(
        default=None, description="Whether this file is the document primary version"
    )
    retrievable: bool | None = Field(default=None, description="Whether retrieval may currently serve this file")

    @classmethod
    def from_orm_extra(cls, model: KnowledgeFile, extra: dict[str, Any]) -> "KnowledgeFileInfoRes":
        """FROMORMModel and Additional Information Create Response Body Instance"""
        knowledge_file_info = cls.model_validate(model)

        knowledge_file_info.creat_user = extra.get("creat_user")
        knowledge_file_info.update_user = extra.get("update_user")

        return knowledge_file_info
