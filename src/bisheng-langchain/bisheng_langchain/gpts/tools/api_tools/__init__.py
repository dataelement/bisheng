from typing import Any, Callable, Dict, List, Tuple

# from .eastmoney import
from bisheng_langchain.gpts.tools.api_tools.firecrawl import FireCrawl
from bisheng_langchain.gpts.tools.api_tools.jina import JinaTool
from bisheng_langchain.gpts.tools.api_tools.silicon_flow import SiliconFlow
from bisheng_langchain.gpts.tools.message.dingding import DingdingMessageTool
from bisheng_langchain.gpts.tools.message.email import EmailMessageTool
from bisheng_langchain.gpts.tools.message.feishu import FeishuMessageTool
from bisheng_langchain.gpts.tools.message.wechat import WechatMessageTool
from langchain_core.tools import BaseTool
from mypy_extensions import KwArg

from .flow import FlowTools
from .macro_data import MacroData
from .sina import StockInfo
from .tianyancha import CompanyInfo

# 筛选出类方法
tianyancha_class_methods = [
    method for method in CompanyInfo.__dict__
    if isinstance(CompanyInfo.__dict__[method], classmethod)
]

_TIAN_YAN_CHA_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {
    f'tianyancha_{name}': (CompanyInfo.get_api_tool, ['api_key'])
    for name in tianyancha_class_methods
}

sina_class_methods = [
    method for method in StockInfo.__dict__ if isinstance(StockInfo.__dict__[method], classmethod)
]

_SINA_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {
    f'sina_{name}': (StockInfo.get_api_tool, [])
    for name in sina_class_methods
}

macro_class_methods = [
    method for method in MacroData.__dict__ if isinstance(MacroData.__dict__[method], classmethod)
]

_MACRO_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {
    f'macro_{name}': (MacroData.get_api_tool, [])
    for name in macro_class_methods
}

_tmp_flow = ['knowledge_retrieve']
_TMP_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {
    f'flow_{name}': (FlowTools.get_api_tool, ['collection_id', 'description'])
    for name in _tmp_flow
}
firecrawl_class_methods = [
    method for method in FireCrawl.__dict__
    if isinstance(FireCrawl.__dict__[method], classmethod)
]

_FIRE_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {
    'fire_search_crawl': (FireCrawl.get_api_tool, ['api_key','maxdepth', 'limit', 'timeout','base_url']),
    'fire_search_scrape': (FireCrawl.get_api_tool, ['api_key','maxdepth', 'limit', 'timeout','base_url'])
}
jina_class_methods = [
    method for method in JinaTool.__dict__
    if isinstance(JinaTool.__dict__[method], classmethod)
]
_JINA_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {
    'jina_get_markdown': (JinaTool.get_api_tool, ['jina_api_key'])
}
silicon_class_methods = [
    method for method in SiliconFlow.__dict__
    if isinstance(SiliconFlow.__dict__[method], classmethod)
]
_SILICON_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {
    'silicon_stable_diffusion': (SiliconFlow.get_api_tool, ['siliconflow_api_key']),
    'silicon_flux': (SiliconFlow.get_api_tool, ['siliconflow_api_key'])
}
dingding_class_methods = [
    method for method in DingdingMessageTool.__dict__
    if isinstance(DingdingMessageTool.__dict__[method], classmethod)
]

_DING_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {
    'ding_send_message': (DingdingMessageTool.get_api_tool, [])
}


email_class_methods = [
    method for method in EmailMessageTool.__dict__
    if isinstance(EmailMessageTool.__dict__[method], classmethod)
]

_EMAIL_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {
    'email_send_email': (EmailMessageTool.get_api_tool, ['email_account','email_password','smtp_server','smtp_port','encrypt_method']),
}

feishu_class_methods = [
    method for method in FeishuMessageTool.__dict__
    if isinstance(FeishuMessageTool.__dict__[method], classmethod)
]

_FEISHU_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {
    'feishu_send_message': (FeishuMessageTool.get_api_tool, ['app_id', 'app_secret']),
    'feishu_get_chat_messages': (FeishuMessageTool.get_api_tool, ['app_id', 'app_secret']),
}

wechat_class_methods = [
    method for method in WechatMessageTool.__dict__
    if isinstance(WechatMessageTool.__dict__[method], classmethod)
]

_WECHAT_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {
    'wechat_send_message': (WechatMessageTool.get_api_tool, [])
}


ALL_API_TOOLS = {}
ALL_API_TOOLS.update(_TIAN_YAN_CHA_TOOLS)
ALL_API_TOOLS.update(_SINA_TOOLS)
ALL_API_TOOLS.update(_MACRO_TOOLS)
ALL_API_TOOLS.update(_TMP_TOOLS)
ALL_API_TOOLS.update(_FIRE_TOOLS)
ALL_API_TOOLS.update(_JINA_TOOLS)
ALL_API_TOOLS.update(_SILICON_TOOLS)
ALL_API_TOOLS.update(_DING_TOOLS)
ALL_API_TOOLS.update(_EMAIL_TOOLS)
ALL_API_TOOLS.update(_FEISHU_TOOLS)
ALL_API_TOOLS.update(_WECHAT_TOOLS)
