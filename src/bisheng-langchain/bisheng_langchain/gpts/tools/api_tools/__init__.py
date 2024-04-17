from typing import Any, Callable, Dict, List, Tuple

# from .eastmoney import
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
ALL_API_TOOLS = {}
ALL_API_TOOLS.update(_TIAN_YAN_CHA_TOOLS)
ALL_API_TOOLS.update(_SINA_TOOLS)
ALL_API_TOOLS.update(_MACRO_TOOLS)
ALL_API_TOOLS.update(_TMP_TOOLS)
