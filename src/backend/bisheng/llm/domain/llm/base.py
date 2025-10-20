from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from bisheng.llm.models import LLMModel, LLMServer, LLMDao


class BishengBase(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, validate_by_name=True, validate_by_alias=True)

    model_id: int = Field(description="后端服务保存的model唯一ID")

    # bisheng强相关的业务参数
    model_info: Optional[LLMModel] = Field(default=None, description="模型配置信息")
    server_info: Optional[LLMServer] = Field(default=None, description="服务提供方信息")

    async def update_model_status(self, status: int, remark: str = ''):
        """更新模型状态"""
        if self.model_info.status != status:
            self.model_info.status = status
            await LLMDao.aupdate_model_status(self.model_id, status, remark[-500:])  # 限制备注长度为500字符

    def sync_update_model_status(self, status: int, remark: str = ''):
        """更新模型状态"""
        if self.model_info.status != status:
            self.model_info.status = status
            LLMDao.update_model_status(self.model_id, status, remark[-500:])
