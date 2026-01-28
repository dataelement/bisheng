from typing import Optional, Type, Any, Dict

from pydantic import Field

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileRead, KnowledgeFile


class KnowledgeFileInfoRes(KnowledgeFileRead):
    """Knowledge Base File Information Response Body"""
    creat_user: Optional[str] = Field(default=None, description='Create user name')
    update_user: Optional[str] = Field(default=None, description='Update user name')

    @classmethod
    def from_orm_extra(cls, model: KnowledgeFile, extra: Dict[str, Any]) -> "KnowledgeFileInfoRes":
        """FROMORMModel and Additional Information Create Response Body Instance"""
        knowledge_file_info = cls.model_validate(model)

        knowledge_file_info.creat_user = extra.get('creat_user')
        knowledge_file_info.update_user = extra.get('update_user')

        return knowledge_file_info
