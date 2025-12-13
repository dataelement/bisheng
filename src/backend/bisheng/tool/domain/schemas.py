from typing import Optional, Dict

from pydantic import BaseModel, Field

from bisheng.tool.domain.const import AuthMethod, AuthType


class TestToolReq(BaseModel):
    server_host: str = Field(default='', description='服务的根地址')
    openapi_schema: Optional[str] = Field(default='', description='openapi schema')
    extra: str = Field(default='', description='Api 对象解析后的extra字段')
    auth_method: int = Field(default=AuthMethod.NO.value, description='认证类型')
    auth_type: Optional[str] = Field(default=AuthType.BASIC.value, description='Auth Type')
    api_key: Optional[str] = Field(default='', description='api key')
    api_location: Optional[str] = Field(default='', description='api location')
    parameter_name: Optional[str] = Field(default='', description='parameter_name')

    request_params: Dict = Field(default=None, description='用户填写的请求参数')
