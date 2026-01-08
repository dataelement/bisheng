from typing import Optional, Dict

from pydantic import BaseModel, Field

from bisheng.tool.domain.const import AuthMethod, AuthType


class TestToolReq(BaseModel):
    server_host: str = Field(default='', description='Root address of the service')
    openapi_schema: Optional[str] = Field(default='', description='openapi schema')
    extra: str = Field(default='', description='Api After the object is parsedextraData field')
    auth_method: int = Field(default=AuthMethod.NO.value, description='Certification Type')
    auth_type: Optional[str] = Field(default=AuthType.BASIC.value, description='Auth Type')
    api_key: Optional[str] = Field(default='', description='api key')
    api_location: Optional[str] = Field(default='', description='api location')
    parameter_name: Optional[str] = Field(default='', description='parameter_name')

    request_params: Dict = Field(default=None, description='User Filled Request Parameters')
