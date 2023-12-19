import contextlib
import json
from typing import Any, Callable, Dict, List, Sequence, Type

from bisheng.chat.config import ChatConfig
from bisheng.interface.agents.base import agent_creator
from bisheng.interface.chains.base import chain_creator
from bisheng.interface.custom_lists import CUSTOM_NODES
from bisheng.interface.importing.utils import get_function, import_by_type
from bisheng.interface.initialize.llm import initialize_vertexai
from bisheng.interface.initialize.vector_store import vecstore_initializer
from bisheng.interface.output_parsers.base import output_parser_creator
from bisheng.interface.retrievers.base import retriever_creator
from bisheng.interface.toolkits.base import toolkits_creator
from bisheng.interface.utils import load_file_into_dict
from bisheng.interface.wrappers.base import wrapper_creator
from bisheng.settings import settings
from bisheng.utils import validate
from langchain.agents import ZeroShotAgent
from langchain.agents import agent as agent_module
from langchain.agents.agent import AgentExecutor
from langchain.agents.agent_toolkits.base import BaseToolkit
from langchain.agents.tools import BaseTool
from langchain.base_language import BaseLanguageModel
from langchain.chains.base import Chain
from langchain.document_loaders.base import BaseLoader
from langchain.schema import BaseOutputParser, Document
from langchain.vectorstores.base import VectorStore
from pydantic import ValidationError

# from bisheng_langchain.document_loaders.elem_unstrcutured_loader import ElemUnstructuredLoaderV0


def instantiate_class(node_type: str, base_type: str, params: Dict) -> Any:
    """Instantiate class from module type and key, and params"""
    params = convert_params_to_sets(params)
    params = convert_kwargs(params)
    if node_type in CUSTOM_NODES:
        if custom_node := CUSTOM_NODES.get(node_type):
            if hasattr(custom_node, 'initialize'):
                return custom_node.initialize(**params)
            return custom_node(**params)

    class_object = import_by_type(_type=base_type, name=node_type)
    return instantiate_based_on_type(class_object, base_type, node_type, params)


def convert_params_to_sets(params):
    """Convert certain params to sets"""
    if 'allowed_special' in params:
        params['allowed_special'] = set(params['allowed_special'])
    if 'disallowed_special' in params:
        params['disallowed_special'] = set(params['disallowed_special'])
    if 'input_node' in params:
        params.pop('input_node')
    return params


def convert_kwargs(params):
    # if *kwargs are passed as a string, convert to dict
    # first find any key that has kwargs or config in it
    kwargs_keys = [key for key in params.keys() if 'kwargs' in key or 'config' in key]
    for key in kwargs_keys:
        if isinstance(params[key], str):
            params[key] = json.loads(params[key])
    return params


def instantiate_based_on_type(class_object, base_type, node_type, params):
    if base_type == 'agents':
        return instantiate_agent(node_type, class_object, params)
    elif base_type == 'prompts':
        return instantiate_prompt(node_type, class_object, params)
    elif base_type == 'tools':
        tool = instantiate_tool(node_type, class_object, params)
        if hasattr(tool, 'name') and isinstance(tool, BaseTool):
            # tool name shouldn't contain spaces
            tool.name = tool.name.replace(' ', '_')
        return tool
    elif base_type == 'toolkits':
        return instantiate_toolkit(node_type, class_object, params)
    elif base_type == 'embeddings':
        return instantiate_embedding(class_object, params)
    elif base_type == 'vectorstores':
        return instantiate_vectorstore(class_object, params)
    elif base_type == 'documentloaders':
        return instantiate_documentloader(class_object, params)
    elif base_type == 'textsplitters':
        return instantiate_textsplitter(class_object, params)
    elif base_type == 'utilities':
        return instantiate_utility(node_type, class_object, params)
    elif base_type == 'chains':
        return instantiate_chains(node_type, class_object, params)
    elif base_type == 'output_parsers':
        return instantiate_output_parser(node_type, class_object, params)
    elif base_type == 'llms':
        return instantiate_llm(node_type, class_object, params)
    elif base_type == 'retrievers':
        return instantiate_retriever(node_type, class_object, params)
    elif base_type == 'memory':
        return instantiate_memory(node_type, class_object, params)
    elif base_type == 'wrappers':
        return instantiate_wrapper(node_type, class_object, params)
    elif base_type == 'input_output':
        return instantiate_input_output(node_type, class_object, params)
    else:
        return class_object(**params)


def instantiate_input_output(node_type, class_object, params):
    return class_object(**params).text()


def instantiate_wrapper(node_type, class_object, params):
    if node_type in wrapper_creator.from_method_nodes:
        method = wrapper_creator.from_method_nodes[node_type]
        if class_method := getattr(class_object, method, None):
            return class_method(**params)
        raise ValueError(f'Method {method} not found in {class_object}')
    return class_object(**params)


def instantiate_output_parser(node_type, class_object, params):
    if node_type in output_parser_creator.from_method_nodes:
        method = output_parser_creator.from_method_nodes[node_type]
        if class_method := getattr(class_object, method, None):
            return class_method(**params)
        raise ValueError(f'Method {method} not found in {class_object}')
    return class_object(**params)


def instantiate_llm(node_type, class_object, params: Dict):
    # This is a workaround so JinaChat works until streaming is implemented
    # if "openai_api_base" in params and "jina" in params["openai_api_base"]:
    # False if condition is True
    if node_type == 'VertexAI':
        return initialize_vertexai(class_object=class_object, params=params)
    # max_tokens sometimes is a string and should be an int
    if 'max_tokens' in params:
        if isinstance(params['max_tokens'], str) and params['max_tokens'].isdigit():
            params['max_tokens'] = int(params['max_tokens'])
        elif not isinstance(params.get('max_tokens'), int):
            params.pop('max_tokens', None)
    # 支持stream
    llm = class_object(**params)
    llm_config = settings.get_from_db('llm_request')
    if isinstance(llm, BaseLanguageModel):
        if hasattr(llm, 'streaming') and isinstance(llm.streaming, bool):
            llm.streaming = llm_config.get(
                'stream') if 'stream' in llm_config else ChatConfig.streaming
        elif hasattr(llm, 'stream') and isinstance(llm.stream, bool):
            llm.stream = llm_config.get(
                'stream') if 'stream' in llm_config else ChatConfig.streaming

    # 支持request_timeout & max_retries
    if hasattr(llm, 'request_timeout') and 'request_timeout' in llm_config:
        if isinstance(llm.request_timeout, str):
            llm.request_timeout = eval(llm_config.get('request_timeout'))
        else:
            llm.request_timeout = llm_config.get('request_timeout')
    if hasattr(llm, 'max_retries') and 'max_retries' in llm_config:
        llm.max_retries = llm_config.get('max_retries')

    return llm


def instantiate_memory(node_type, class_object, params):
    # process input_key and output_key to remove them if
    # they are empty strings
    if node_type == 'ConversationEntityMemory':
        params.pop('memory_key', None)

    for key in ['input_key', 'output_key']:
        if key in params and (params[key] == '' or not params[key]):
            params.pop(key)

    try:
        if 'retriever' in params and hasattr(params['retriever'], 'as_retriever'):
            params['retriever'] = params['retriever'].as_retriever()
        return class_object(**params)
    # I want to catch a specific attribute error that happens
    # when the object does not have a cursor attribute
    except Exception as exc:
        if "object has no attribute 'cursor'" in str(exc) or 'object has no field "conn"' in str(
                exc):
            raise AttributeError(
                ('Failed to build connection to database.'
                 f' Please check your connection string and try again. Error: {exc}')) from exc
        raise exc


def instantiate_retriever(node_type, class_object, params):
    for key, value in params.items():
        if 'retriever' in key and hasattr(value, 'as_retriever'):
            params[key] = value.as_retriever()
    if node_type in retriever_creator.from_method_nodes:
        method = retriever_creator.from_method_nodes[node_type]
        if class_method := getattr(class_object, method, None):
            return class_method(**params)
        raise ValueError(f'Method {method} not found in {class_object}')
    return class_object(**params)


def instantiate_chains(node_type, class_object: Type[Chain], params: Dict):
    if 'retriever' in params and hasattr(params['retriever'], 'as_retriever'):
        params['retriever'] = params['retriever'].as_retriever()
    # dict 转换
    if 'headers' in params and isinstance(params['headers'], str):
        params['headers'] = eval(params['headers'])
    if node_type == 'ConversationalRetrievalChain':
        params['get_chat_history'] = str
        params['combine_docs_chain_kwargs'] = {
            'prompt': params.pop('combine_docs_chain_kwargs', None)
        }
    if node_type in chain_creator.from_method_nodes:
        method = chain_creator.from_method_nodes[node_type]
        if class_method := getattr(class_object, method, None):
            return class_method(**params)
        raise ValueError(f'Method {method} not found in {class_object}')

    return class_object(**params)


def instantiate_agent(node_type, class_object: Type[agent_module.Agent], params: Dict):
    if node_type in agent_creator.from_method_nodes:
        method = agent_creator.from_method_nodes[node_type]
        if class_method := getattr(class_object, method, None):
            agent = class_method(**params)
            tools = params.get('tools', [])
            return AgentExecutor.from_agent_and_tools(agent=agent,
                                                      tools=tools,
                                                      handle_parsing_errors=True)
    return load_agent_executor(class_object, params)


def instantiate_prompt(node_type, class_object, params: Dict):
    if node_type == 'ZeroShotPrompt':
        if 'tools' not in params:
            params['tools'] = []
        return ZeroShotAgent.create_prompt(**params)
    elif 'MessagePromptTemplate' in node_type:
        # Then we only need the template
        from_template_params = {'template': params.pop('prompt', params.pop('template', ''))}

        if not from_template_params.get('template'):
            raise ValueError('Prompt template is required')
        prompt = class_object.from_template(**from_template_params)

    elif node_type == 'ChatPromptTemplate':
        prompt = class_object.from_messages(**params)
    else:
        prompt = class_object(**params)

    format_kwargs: Dict[str, Any] = {}
    for input_variable in prompt.input_variables:
        if input_variable in params:
            variable = params[input_variable]
            if isinstance(variable, str):
                format_kwargs[input_variable] = variable
            elif isinstance(variable, BaseOutputParser) and hasattr(variable,
                                                                    'get_format_instructions'):
                format_kwargs[input_variable] = variable.get_format_instructions()
            elif isinstance(variable, List) and all(
                    isinstance(item, Document) for item in variable):
                # Format document to contain page_content and metadata
                # as one string separated by a newline
                if len(variable) > 1:
                    content = '\n'.join(
                        [item.page_content for item in variable if item.page_content])
                else:
                    if not variable:
                        format_kwargs[input_variable] = ''
                        continue
                    content = variable[0].page_content
                    # content could be a json list of strings
                    with contextlib.suppress(json.JSONDecodeError):
                        content = json.loads(content)
                        if isinstance(content, list):
                            content = ','.join([str(item) for item in content])
                format_kwargs[input_variable] = content
                # handle_keys will be a list but it does not exist yet
                # so we need to create it

            if (isinstance(variable, List) and
                    all(isinstance(item, Document)
                        for item in variable)) or (isinstance(variable, BaseOutputParser) and
                                                   hasattr(variable, 'get_format_instructions')):
                if 'handle_keys' not in format_kwargs:
                    format_kwargs['handle_keys'] = []

                # Add the handle_keys to the list
                format_kwargs['handle_keys'].append(input_variable)

    return prompt, format_kwargs


def instantiate_tool(node_type, class_object: Type[BaseTool], params: Dict):
    if node_type == 'JsonSpec':
        if file_dict := load_file_into_dict(params.pop('path')):
            params['dict_'] = file_dict
        else:
            raise ValueError('Invalid file')
        return class_object(**params)
    elif node_type == 'PythonFunctionTool':
        params['func'] = get_function(params.get('code'))
        return class_object(**params)
    elif node_type == 'PythonFunction':
        function_string = params['code']
        if isinstance(function_string, str):
            return validate.eval_function(function_string)
        raise ValueError('Function should be a string')
    elif node_type.lower() == 'tool':
        return class_object(**params)
    return class_object(**params)


def instantiate_toolkit(node_type, class_object: Type[BaseToolkit], params: Dict):
    loaded_toolkit = class_object(**params)
    # Commenting this out for now to use toolkits as normal tools
    # if toolkits_creator.has_create_function(node_type):
    #     return load_toolkits_executor(node_type, loaded_toolkit, params)
    if isinstance(loaded_toolkit, BaseToolkit):
        return loaded_toolkit.get_tools()
    return loaded_toolkit


def instantiate_embedding(class_object, params: Dict):
    # params.pop('model', None)
    try:
        return class_object(**params)
    except ValidationError:
        params = {key: value for key, value in params.items() if key in class_object.__fields__}
        return class_object(**params)


def instantiate_vectorstore(class_object: Type[VectorStore], params: Dict):
    search_kwargs = params.pop('search_kwargs', {})
    if 'documents' not in params:
        params['documents'] = []

    if initializer := vecstore_initializer.get(class_object.__name__):
        vecstore = initializer(class_object, params)
    else:
        if 'texts' in params:
            params['documents'] = params.pop('texts')
        vecstore = class_object.from_documents(**params)

    # ! This might not work. Need to test
    if search_kwargs and hasattr(vecstore, 'as_retriever'):
        vecstore = vecstore.as_retriever(search_kwargs=search_kwargs)

    return vecstore


def instantiate_documentloader(class_object: Type[BaseLoader], params: Dict):
    if 'file_filter' in params:
        # file_filter will be a string but we need a function
        # that will be used to filter the files using file_filter
        # like lambda x: x.endswith(".txt") but as we don't know
        # anything besides the string, we will simply check if the string is
        # in x and if it is, we will return True
        file_filter = params.pop('file_filter')
        extensions = file_filter.split(',')
        params['file_filter'] = lambda x: any(extension.strip() in x for extension in extensions)
    if 'file_path' in params:
        file_path = params['file_path']
        if isinstance(file_path, list):
            file_name = file_path[1]
            params['file_path'] = file_path[0]
            if class_object.__name__ == 'ElemUnstructuredLoaderV0':
                params['file_name'] = file_name
    metadata = params.pop('metadata', None)
    if metadata and isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError as exc:
            raise ValueError('The metadata you provided is not a valid JSON string.') from exc
    # make it success when file not present
    if 'file_path' in params and not params['file_path']:
        return []
    docs = class_object(**params).load()
    # Now if metadata is an empty dict, we will not add it to the documents
    if metadata:
        for doc in docs:
            # If the document already has metadata, we will not overwrite it
            if not doc.metadata:
                doc.metadata = metadata
            else:
                doc.metadata.update(metadata)

    return docs


def instantiate_textsplitter(
    class_object,
    params: Dict,
):
    try:
        documents = params.pop('documents')
        if not documents:
            return []
    except KeyError as exc:
        raise ValueError('The source you provided did not load correctly or was empty.'
                         'Try changing the chunk_size of the Text Splitter.') from exc

    if ('separator_type' in params and
            params['separator_type'] == 'Text') or 'separator_type' not in params:
        params.pop('separator_type', None)
        # separators might come in as an escaped string like \\n
        # so we need to convert it to a string
        if 'separators' in params:
            params['separators'] = (params['separators'].encode().decode('unicode-escape'))
        text_splitter = class_object(**params)
    else:
        from langchain.text_splitter import Language

        language = params.pop('separator_type', None)
        params['language'] = Language(language)
        params.pop('separators', None)

        text_splitter = class_object.from_language(**params)
    return text_splitter.split_documents(documents)


def instantiate_utility(node_type, class_object, params: Dict):
    if node_type == 'SQLDatabase':
        return class_object.from_uri(params.pop('uri'))
    return class_object(**params)


def replace_zero_shot_prompt_with_prompt_template(nodes):
    """Replace ZeroShotPrompt with PromptTemplate"""
    for node in nodes:
        if node['data']['type'] == 'ZeroShotPrompt':
            # Build Prompt Template
            tools = [
                tool for tool in nodes if tool['type'] != 'chatOutputNode' and
                'Tool' in tool['data']['node']['base_classes']
            ]
            node['data'] = build_prompt_template(prompt=node['data'], tools=tools)
            break
    return nodes


def load_agent_executor(agent_class: type[agent_module.Agent], params, **kwargs):
    """Load agent executor from agent class, tools and chain"""
    allowed_tools: Sequence[BaseTool] = params.get('allowed_tools', [])
    llm_chain = params['llm_chain']
    # agent has hidden args for memory. might need to be support
    # memory = params["memory"]
    # if allowed_tools is not a list or set, make it a list
    if not isinstance(allowed_tools, (list, set)) and isinstance(allowed_tools, BaseTool):
        allowed_tools = [allowed_tools]
    tool_names = [tool.name for tool in allowed_tools]
    # Agent class requires an output_parser but Agent classes
    # have a default output_parser.
    agent = agent_class(allowed_tools=tool_names, llm_chain=llm_chain)  # type: ignore
    return AgentExecutor.from_agent_and_tools(
        agent=agent,
        tools=allowed_tools,
        handle_parsing_errors=True,
        # memory=memory,
        **kwargs,
    )


def load_toolkits_executor(node_type: str, toolkit: BaseToolkit, params: dict):
    create_function: Callable = toolkits_creator.get_create_function(node_type)
    if llm := params.get('llm'):
        return create_function(llm=llm, toolkit=toolkit)


def build_prompt_template(prompt, tools):
    """Build PromptTemplate from ZeroShotPrompt"""
    prefix = prompt['node']['template']['prefix']['value']
    suffix = prompt['node']['template']['suffix']['value']
    format_instructions = prompt['node']['template']['format_instructions']['value']

    tool_strings = '\n'.join([
        f"{tool['data']['node']['name']}: {tool['data']['node']['description']}" for tool in tools
    ])
    tool_names = ', '.join([tool['data']['node']['name'] for tool in tools])
    format_instructions = format_instructions.format(tool_names=tool_names)
    value = '\n\n'.join([prefix, tool_strings, format_instructions, suffix])

    prompt['type'] = 'PromptTemplate'

    prompt['node'] = {
        'template': {
            '_type': 'prompt',
            'input_variables': {
                'type': 'str',
                'required': True,
                'placeholder': '',
                'list': True,
                'show': False,
                'multiline': False,
            },
            'output_parser': {
                'type': 'BaseOutputParser',
                'required': False,
                'placeholder': '',
                'list': False,
                'show': False,
                'multline': False,
                'value': None,
            },
            'template': {
                'type': 'str',
                'required': True,
                'placeholder': '',
                'list': False,
                'show': True,
                'multiline': True,
                'value': value,
            },
            'template_format': {
                'type': 'str',
                'required': False,
                'placeholder': '',
                'list': False,
                'show': False,
                'multline': False,
                'value': 'f-string',
            },
            'validate_template': {
                'type': 'bool',
                'required': False,
                'placeholder': '',
                'list': False,
                'show': False,
                'multline': False,
                'value': True,
            },
        },
        'description': 'Schema to represent a prompt for an LLM.',
        'base_classes': ['BasePromptTemplate'],
    }

    return prompt
