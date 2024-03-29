import inspect
from typing import Any, Callable, Dict, List, Tuple

# from .eastmoney import
from langchain_core.tools import BaseTool
from mypy_extensions import KwArg

from .sina import StockInfo
from .tianyancha import CompanyInfo

# 筛选出类方法
tianyancha_class_methods = [method for method in CompanyInfo.__dict__ if isinstance(CompanyInfo.__dict__[method], classmethod)]

_TIAN_YAN_CHA_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {
    f'tianyancha.{name}': (CompanyInfo.get_api_tool, ['api_key']) for name in tianyancha_class_methods
}

sina_class_methods = [method for method in StockInfo.__dict__ if isinstance(StockInfo.__dict__[method], classmethod)]

_SINA_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {
    f'sina.{name}': (StockInfo.get_api_tool, []) for name in sina_class_methods
}

ALL_API_TOOLS = {}
ALL_API_TOOLS.update(_TIAN_YAN_CHA_TOOLS)
ALL_API_TOOLS.update(_SINA_TOOLS)
# eastomney_class_methods = [
#     attr for attr in dir(StockInfo) if inspect.ismethod(getattr(StockInfo, attr))
# ]
