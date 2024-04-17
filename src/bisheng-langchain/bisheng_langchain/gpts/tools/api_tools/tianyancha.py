"""tianyancha api"""
from __future__ import annotations

from typing import Any, Dict, Type

from bisheng_langchain.utils.requests import Requests, RequestsWrapper
from langchain_core.pydantic_v1 import BaseModel, Field, root_validator

from .base import APIToolBase


class InputArgs(BaseModel):
    """args_schema"""
    query: str = Field(description='搜索关键字（公司名称、公司id、注册号或社会统一信用代码）')


class CompanyInfo(APIToolBase):
    """Manage tianyancha company client."""
    api_key: str = None
    args_schema: Type[BaseModel] = InputArgs

    @root_validator(pre=True)
    def build_header(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """Build headers that were passed in."""
        if not values.get('api_key'):
            raise ValueError('Parameters api_key should be specified give.')

        headers = values.get('headers', {})
        headers.update({'Authorization': values['api_key']})
        values['headers'] = headers
        return values

    @root_validator()
    def validate_environment(cls, values: Dict) -> Dict:
        """Validate that api key and python package exists in environment."""
        timeout = values.get('request_timeout', 30)
        if not values.get('client'):
            values['client'] = Requests(headers=values['headers'], request_timeout=timeout)
        if not values.get('async_client'):
            values['async_client'] = RequestsWrapper(headers=values['headers'],
                                                     request_timeout=timeout)
        return values

    @classmethod
    def search_company(cls, api_key: str, pageNum: int = 1, pageSize: int = 20) -> CompanyInfo:
        """可以通过关键词获取企业列表，企业列表包括公司名称或ID、类型、成立日期、经营状态、统一社会信用代码等字段的详细信息"""
        url = 'http://open.api.tianyancha.com/services/open/search/2.0'
        input_key = 'word'
        params = {}
        params['pageSize'] = pageSize
        params['pageNum'] = pageNum

        return cls(url=url, api_key=api_key, input_key=input_key, params=params)

    @classmethod
    def get_company_baseinfo(cls, api_key: str) -> CompanyInfo:
        """可以通过公司名称或ID获取企业基本信息，企业基本信息包括公司名称或ID、类型、成立日期、经营状态、注册资本、法人、工商注册号、统一社会信用代码、组织机构代码、纳税人识别号等字段信息"""
        url = 'http://open.api.tianyancha.com/services/open/ic/baseinfo/normal'
        input_key = 'keyword'
        params = {}

        return cls(url=url, api_key=api_key, input_key=input_key, params=params)

    @classmethod
    def ip_rights(cls, api_key: str) -> CompanyInfo:
        """可以通过公司名称或ID获取包含商标、专利、作品著作权、软件著作权、网站备案等维度的相关信息"""
        url = 'http://open.api.tianyancha.com/services/open/cb/ipr/3.0'
        input_key = 'keyword'

        return cls(url=url, api_key=api_key, input_key=input_key, params={})

    @classmethod
    def judicial_risk(cls, api_key: str) -> CompanyInfo:
        """可以通过公司名称或ID获取包含法律诉讼、法院公告、开庭公告、失信人、被执行人、立案信息、送达公告等维度的相关信息"""
        url = 'http://open.api.tianyancha.com/services/open/cb/judicial/2.0'
        return cls(url=url, api_key=api_key)

    @classmethod
    def ic_info(cls, api_key: str) -> CompanyInfo:
        """可以通过公司名称或ID获取包含企业基本信息、主要人员、股东信息、对外投资、分支机构等维度的相关信息"""
        url = 'http://open.api.tianyancha.com/services/open/cb/ic/2.0'

        return cls(url=url, api_key=api_key)

    @classmethod
    def law_suit_case(cls, api_key: str, pageSize: int = 20, pageNum: int = 1) -> CompanyInfo:
        """可以通过公司名称或ID获取企业法律诉讼信息，法律诉讼包括案件名称、案由、案件身份、案号等字段的详细信息"""
        url = 'http://open.api.tianyancha.com/services/open/jr/lawSuit/3.0'
        params = {}
        params['pageSize'] = pageSize
        params['pageNum'] = pageNum
        return cls(url=url, api_key=api_key, params=params)

    @classmethod
    def company_change_info(cls,
                            api_key: str,
                            pageSize: int = 20,
                            pageNum: int = 1) -> CompanyInfo:
        """可以通过公司名称或ID获取企业变更记录，变更记录包括工商变更事项、变更前后信息等字段的详细信息"""
        url = 'http://open.api.tianyancha.com/services/open/ic/changeinfo/2.0'
        params = {}
        params['pageSize'] = pageSize
        params['pageNum'] = pageNum
        return cls(url=url, api_key=api_key, params=params)

    @classmethod
    def company_holders(cls, api_key: str, pageSize: int = 20, pageNum: int = 1) -> CompanyInfo:
        """可以通过公司名称或ID获取企业股东信息，股东信息包括股东名、出资比例、出资金额、股东总数等字段的详细信息"""
        url = 'http://open.api.tianyancha.com/services/open/ic/holder/2.0'
        params = {}
        params['pageSize'] = pageSize
        params['pageNum'] = pageNum
        return cls(url=url, api_key=api_key, params=params)

    @classmethod
    def all_companys_by_company(cls, api_key: str, pageSize: int = 20, pageNum: int = 1):
        """可以通过公司名称和人名获取企业人员的所有相关公司，包括其担任法人、股东、董监高的公司信息"""
        url = 'http://open.api.tianyancha.com/services/v4/open/allCompanys'
        input_key = 'humanName'
        params = {}
        params['pageSize'] = pageSize
        params['pageNum'] = pageNum

        class InputArgs(BaseModel):
            """args_schema"""
            query: str = Field(description='human who you want to search')
            name: str = Field(description='company name which human worked')

        return cls(url=url,
                   api_key=api_key,
                   params=params,
                   input_key=input_key,
                   args_schema=InputArgs)

    @classmethod
    def riskinfo(cls, api_key: str) -> CompanyInfo:
        """可以通过关键字（公司名称、公司id、注册号或社会统一信用代码）获取企业相关天眼风险列表，包括企业自身/周边/预警风险信息。"""
        url = 'http://open.api.tianyancha.com/services/open/risk/riskInfo/2.0'
        return cls(url=url, api_key=api_key)
