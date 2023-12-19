# This module is used to import any langchain class by name.

import importlib
from typing import Any, Type

from bisheng.interface.wrappers.base import wrapper_creator
from bisheng.utils import validate
from langchain import PromptTemplate
from langchain.agents import Agent
from langchain.base_language import BaseLanguageModel
from langchain.chains.base import Chain
from langchain.chat_models.base import BaseChatModel
from langchain.tools import BaseTool


def import_module(module_path: str) -> Any:
    """Import module from module path"""
    if 'from' not in module_path:
        # Import the module using the module path
        return importlib.import_module(module_path)
    # Split the module path into its components
    _, module_path, _, object_name = module_path.split()

    # Import the module using the module path
    module = importlib.import_module(module_path)

    return getattr(module, object_name)


def import_by_type(_type: str, name: str) -> Any:
    from bisheng_langchain import chat_models
    """Import class by type and name"""
    if _type is None:
        raise ValueError(f'Type cannot be None. Check if {name} is in the config file.')
    func_dict = {
        'agents': import_agent,
        'prompts': import_prompt,
        'llms': {
            'llm': import_llm,
            'chat': import_chat_llm,
            'contribute': import_chain_contribute_llm
        },
        'tools': import_tool,
        'chains': import_chain,
        'toolkits': import_toolkit,
        'wrappers': import_wrapper,
        'memory': import_memory,
        'embeddings': import_embedding,
        'vectorstores': import_vectorstore,
        'documentloaders': import_documentloader,
        'textsplitters': import_textsplitter,
        'utilities': import_utility,
        'output_parsers': import_output_parser,
        'retrievers': import_retriever,
    }
    if _type == 'llms':
        key = 'contribute' if name in chat_models.__all__ else 'chat' if 'chat' in name.lower(
        ) else 'llm'
        loaded_func = func_dict[_type][key]  # type: ignore
    else:
        loaded_func = func_dict[_type]

    return loaded_func(name)


def import_output_parser(output_parser: str) -> Any:
    """Import output parser from output parser name"""
    return import_module(f'from langchain.output_parsers import {output_parser}')


def import_chat_llm(llm: str) -> BaseChatModel:
    """Import chat llm from llm name"""
    return import_class(f'langchain.chat_models.{llm}')


def import_chain_contribute_llm(llm: str) -> BaseChatModel:
    """Import chat llm from llm name"""
    return import_class(f'bisheng_langchain.chat_models.{llm}')


def import_retriever(retriever: str) -> Any:
    from bisheng.interface.retrievers.base import retriever_creator
    if retriever in retriever_creator.type_to_loader_dict:
        return retriever_creator.type_to_loader_dict[retriever]
    """Import retriever from retriever name"""
    return import_module(f'from langchain.retrievers import {retriever}')


def import_memory(memory: str) -> Any:
    """Import memory from memory name"""
    return import_module(f'from langchain.memory import {memory}')


def import_class(class_path: str) -> Any:
    """Import class from class path"""
    module_path, class_name = class_path.rsplit('.', 1)
    module = import_module(module_path)
    return getattr(module, class_name)


def import_prompt(prompt: str) -> Type[PromptTemplate]:
    """Import prompt from prompt name"""
    from bisheng.interface.prompts.custom import CUSTOM_PROMPTS

    if prompt == 'ZeroShotPrompt':
        return import_class('langchain.prompts.PromptTemplate')
    elif prompt in CUSTOM_PROMPTS:
        return CUSTOM_PROMPTS[prompt]
    return import_class(f'langchain.prompts.{prompt}')


def import_wrapper(wrapper: str) -> Any:
    """Import wrapper from wrapper name"""
    if (isinstance(wrapper_creator.type_dict, dict) and wrapper in wrapper_creator.type_dict):
        return wrapper_creator.type_dict.get(wrapper)


def import_toolkit(toolkit: str) -> Any:
    """Import toolkit from toolkit name"""
    return import_module(f'from langchain.agents.agent_toolkits import {toolkit}')


def import_agent(agent: str) -> Agent:
    """Import agent from agent name"""
    # check for custom agent

    return import_class(f'langchain.agents.{agent}')


def import_llm(llm: str) -> BaseLanguageModel:
    """Import llm from llm name"""
    return import_class(f'langchain.llms.{llm}')


def import_tool(tool: str) -> BaseTool:
    """Import tool from tool name"""
    from bisheng.interface.tools.base import tool_creator

    if tool in tool_creator.type_to_loader_dict:
        return tool_creator.type_to_loader_dict[tool]['fcn']

    return import_class(f'langchain.tools.{tool}')


def import_chain(chain: str) -> Type[Chain]:
    """Import chain from chain name"""
    from bisheng.interface.chains.custom import CUSTOM_CHAINS

    if chain in CUSTOM_CHAINS:
        return CUSTOM_CHAINS[chain]

    from bisheng_langchain import chains
    if chain in chains.__all__:
        return import_class(f'bisheng_langchain.chains.{chain}')

    return import_class(f'langchain.chains.{chain}')


def import_embedding(embedding: str) -> Any:
    """Import embedding from embedding name"""
    from bisheng_langchain import embeddings
    if embedding in embeddings.__all__:
        return import_class(f'bisheng_langchain.embeddings.{embedding}')
    return import_class(f'langchain.embeddings.{embedding}')


def import_vectorstore(vectorstore: str) -> Any:
    """Import vectorstore from vectorstore name"""
    from bisheng_langchain import vectorstores
    if vectorstore in vectorstores.__all__:
        return import_class(f'bisheng_langchain.vectorstores.{vectorstore}')
    return import_class(f'langchain.vectorstores.{vectorstore}')


def import_documentloader(documentloader: str) -> Any:
    """Import documentloader from documentloader name"""
    from bisheng_langchain import document_loaders

    if documentloader in document_loaders.__all__:
        return import_class(f'bisheng_langchain.document_loaders.{documentloader}')
    return import_class(f'langchain.document_loaders.{documentloader}')


def import_textsplitter(textsplitter: str) -> Any:
    """Import textsplitter from textsplitter name"""
    return import_class(f'langchain.text_splitter.{textsplitter}')


def import_utility(utility: str) -> Any:
    """Import utility from utility name"""
    if utility == 'SQLDatabase':
        return import_class(f'langchain.sql_database.{utility}')
    return import_class(f'langchain.utilities.{utility}')


def get_function(code):
    """Get the function"""
    function_name = validate.extract_function_name(code)

    return validate.create_function(code, function_name)
