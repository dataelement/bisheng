import inspect
from typing import Any, Callable, Dict, List, Tuple

# from .eastmoney import
from langchain_core.tools import BaseTool
from mypy_extensions import KwArg

from .macro_data import MacroData
from .sina import StockInfo
from .tianyancha import CompanyInfo

# 筛选出类方法
tianyancha_class_methods = [
    attr for attr in dir(CompanyInfo) if inspect.ismethod(getattr(CompanyInfo, attr))
]

_TIAN_YAN_CHA_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {
    f'tianyancha.{name}': (CompanyInfo.get_api_tool, ['api_key'])
    for name in tianyancha_class_methods
}

sina_class_methods = [
    attr for attr in dir(StockInfo) if inspect.ismethod(getattr(StockInfo, attr))
]

_SINA_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {
    f'sina.{name}': (StockInfo.get_api_tool, [])
    for name in sina_class_methods
}

macro_class_methods = [
    attr for attr in dir(MacroData) if inspect.ismethod(getattr(MacroData, attr))
]

_MACRO_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {
    f'macro.{name}': (MacroData.get_api_tool, [])
    for name in macro_class_methods
}

ALL_API_TOOLS = {}
ALL_API_TOOLS.update(_TIAN_YAN_CHA_TOOLS)
ALL_API_TOOLS.update(_SINA_TOOLS)
ALL_API_TOOLS.update(_MACRO_TOOLS)
