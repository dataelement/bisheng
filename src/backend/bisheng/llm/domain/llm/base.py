from typing import Optional, Dict

from pydantic import BaseModel, Field, ConfigDict
from typing_extensions import Self

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from ..models import LLMModel, LLMServer, LLMDao


class BishengBase(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, validate_by_name=True, validate_by_alias=True)

    model_id: int = Field(description="Saved by backend servicemodelUniqueness quantificationID")
    model_name: str = Field(default='', description='model name in mysql')

    # field for telemetry logging
    app_id: str = Field(..., description='application id')
    app_type: ApplicationTypeEnum = Field(..., description='application type')
    app_name: str = Field(..., description='application name')
    user_id: int = Field(..., description='invoke user id')

    # bishengStrongly related business parameters
    model_info: Optional[LLMModel] = Field(default=None, description="Model Configuration Information")
    server_info: Optional[LLMServer] = Field(default=None, description="Service Provider Information")

    @classmethod
    async def get_class_instance(cls, **kwargs: Dict) -> Self:
        model_id: int | None = kwargs.pop('model_id', None)
        model_info, server_info = await cls.get_model_server_info(model_id)
        instance = cls(
            model_id=model_id,
            model_name=model_info.model_name,
            model_info=model_info,
            server_info=server_info,
            **kwargs
        )
        return instance

    @classmethod
    async def get_model_server_info(cls, model_id: int | None) -> tuple[LLMModel | None, LLMServer | None]:
        model_info = None
        server_info = None
        if not model_id:
            return model_info, server_info
        model_info = await LLMDao.aget_model_by_id(model_id)
        if model_info:
            server_info = await LLMDao.aget_server_by_id(model_info.server_id)
        return model_info, server_info

    @classmethod
    def get_model_server_info_sync(cls, model_id: int | None) -> tuple[LLMModel | None, LLMServer | None]:
        model_info = None
        server_info = None
        if not model_id:
            return model_info, server_info
        model_info = LLMDao.get_model_by_id(model_id)
        if model_info:
            server_info = LLMDao.get_server_by_id(model_info.server_id)
        return model_info, server_info

    async def update_model_status(self, status: int, remark: str = ''):
        """Update model status"""
        if self.model_info.status != status:
            self.model_info.status = status
            await LLMDao.aupdate_model_status(self.model_id, status, remark[-500:])  # Limit note length to500characters. 

    def sync_update_model_status(self, status: int, remark: str = ''):
        """Update model status"""
        if self.model_info.status != status:
            self.model_info.status = status
            LLMDao.update_model_status(self.model_id, status, remark[-500:])

    def get_server_info_config(self):
        if self.server_info and self.server_info.config:
            return self.server_info.config
        return {}

    def get_model_info_config(self):
        if self.model_info and self.model_info.config:
            return self.model_info.config
        return {}
