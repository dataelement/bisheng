from typing import Optional, Type, Any, Dict

from pydantic import Field

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileRead, KnowledgeFile


class KnowledgeFileInfoRes(KnowledgeFileRead):
    """知识库文件信息响应体"""
    creat_user: Optional[str] = Field(default=None, description='创建用户名称')
    update_user: Optional[str] = Field(default=None, description='更新用户名称')

    @classmethod
    def from_orm_extra(cls, model: KnowledgeFile, extra: Dict[str, Any]) -> "KnowledgeFileInfoRes":
        """从ORM模型和额外信息创建响应体实例"""
        knowledge_file_info = cls.model_validate(model)

        knowledge_file_info.creat_user = extra.get('creat_user')
        knowledge_file_info.update_user = extra.get('update_user')

        return knowledge_file_info
