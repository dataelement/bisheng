from typing import Any, List, Optional

from langchain_core.callbacks import Callbacks
from langchain_core.language_models import BaseLanguageModel
from langchain_core.tools import BaseTool


def load_tools(
    tool_names: List[str],
    llm: Optional[BaseLanguageModel] = None,
    callbacks: Callbacks = None,
    **kwargs: Any,
) -> List[BaseTool]:
    """Load tools based on their name.

    Tools allow agents to interact with various resources and services like
    APIs, databases, file systems, etc.

    Please scope the permissions of each tools to the minimum required for the
    application.

    For example, if an application only needs to read from a database,
    the database tool should not be given write permissions. Moreover
    consider scoping the permissions to only allow accessing specific
    tables and impose user-level quota for limiting resource usage.

    Please read the APIs of the individual tools to determine which configuration
    they support.

    See [Security](https://python.langchain.com/docs/security) for more information.

    Args:
        tool_names: name of tools to load.
        llm: An optional language model, may be needed to initialize certain tools.
        callbacks: Optional callback manager or list of callback handlers.
            If not provided, default global callback manager will be used.

    Returns:
        List of tools.
    """
    tools = []
    # callbacks = _handle_callbacks(callback_manager=kwargs.get('callback_manager'),
    #                               callbacks=callbacks)
    # print(_BASE_TOOLS)
    # print(1)
    for name in tool_names:
        pass

    # if callbacks is not None:
    #     for tool in tools:
    #         tool.callbacks = callbacks
    return tools
