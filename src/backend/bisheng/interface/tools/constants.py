from bisheng.interface.importing.utils import import_class
from bisheng.interface.tools.custom import PythonFunction, PythonFunctionTool
from langchain_community.tools import Tool
from langchain_community.agent_toolkits.load_tools import (_BASE_TOOLS, _EXTRA_LLM_TOOLS, _EXTRA_OPTIONAL_TOOLS,
                                                           _LLM_TOOLS)
from langchain_community import tools
from langchain_community.tools.json.tool import JsonSpec
from langchain_experimental import tools as python_tools

FILE_TOOLS = {'JsonSpec': JsonSpec}
CUSTOM_TOOLS = {
    'Tool': Tool,
    'PythonFunctionTool': PythonFunctionTool,
    'PythonFunction': PythonFunction,
}

OTHER_TOOLS = {tool: import_class(f'langchain_community.tools.{tool}') for tool in tools.__all__}
PYTHON_TOOLS = {
    tool: import_class(f'langchain_experimental.tools.{tool}')
    for tool in python_tools.__all__
}

ALL_TOOLS_NAMES = {
    **_BASE_TOOLS,
    **_LLM_TOOLS,  # type: ignore
    **{
        k: v[0]
        for k, v in _EXTRA_LLM_TOOLS.items()
    },  # type: ignore
    **{
        k: v[0]
        for k, v in _EXTRA_OPTIONAL_TOOLS.items()
    },
    **CUSTOM_TOOLS,
    **FILE_TOOLS,  # type: ignore
    **OTHER_TOOLS,
    **PYTHON_TOOLS
}
