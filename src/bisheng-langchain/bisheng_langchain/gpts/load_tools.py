import warnings
from typing import Any, List, Optional

from langchain_core.callbacks import BaseCallbackManager, Callbacks
from langchain_core.language_models import BaseLanguageModel
from langchain_core.tools import BaseTool

from .api_tools import API_TOOLS


def _handle_callbacks(callback_manager: Optional[BaseCallbackManager],
                      callbacks: Callbacks) -> Callbacks:
    if callback_manager is not None:
        warnings.warn(
            'callback_manager is deprecated. Please use callbacks instead.',
            DeprecationWarning,
        )
        if callbacks is not None:
            raise ValueError('Cannot specify both callback_manager and callbacks arguments.')
        return callback_manager
    return callbacks


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
    callbacks = _handle_callbacks(callback_manager=kwargs.get('callback_manager'),
                                  callbacks=callbacks)

    for name in tool_names:
        if name in API_TOOLS:
            _get_api_tool_func, extra_keys = API_TOOLS[name]
            missing_keys = set(extra_keys).difference(kwargs)
            if missing_keys:
                raise ValueError(f'Tool {name} requires some parameters that were not '
                                 f'provided: {missing_keys}')
            mini_kwargs = {k: kwargs[k] for k in extra_keys}
            tool = _get_api_tool_func(name=name.split('.')[-1], **mini_kwargs)
            tools.append(tool)

    if callbacks is not None:
        for tool in tools:
            tool.callbacks = callbacks
    return tools
