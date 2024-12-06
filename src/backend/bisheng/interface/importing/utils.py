# This module is used to import any langchain class by name.

import importlib
from typing import Any, ClassVar, Dict, Type

from bisheng.interface.custom import CustomComponent
from bisheng.interface.wrappers.base import wrapper_creator
from bisheng.utils import validate
from langchain.agents import Agent
from langchain.base_language import BaseLanguageModel
from langchain.chains.base import Chain
from langchain.chat_models.base import BaseChatModel
from langchain.prompts import PromptTemplate
from langchain_community.tools import BaseTool


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
    func_dict: ClassVar[Dict] = {
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
        'autogen_roles': import_autogenRoles,
        'input_output': import_inputoutput,
        'custom_components': import_custom_component,
    }
    if _type == 'llms':
        key = 'contribute' if name in chat_models.__all__ else 'chat' if 'chat' in name.lower(
        ) else 'llm'
        loaded_func = func_dict[_type][key]  # type: ignore
    else:
        loaded_func = func_dict[_type]

    return loaded_func(name)


def import_custom_component(custom_component: str) -> CustomComponent:
    """Import custom component from custom component name"""
    return import_class('bisheng.interface.custom.custom_component.CustomComponent')


def import_inputoutput(input_output: str) -> Any:
    """Import output parser from output parser name"""
    from bisheng.interface.inputoutput.base import input_output_creator
    return input_output_creator.type_to_loader_dict[input_output]


def import_output_parser(output_parser: str) -> Any:
    """Import output parser from output parser name"""
    from bisheng.interface.output_parsers.base import output_parser_creator
    if output_parser in output_parser_creator.type_to_loader_dict:
        return output_parser_creator.type_to_loader_dict[output_parser]
    return import_module(f'from langchain_community.output_parsers import {output_parser}')


def import_chat_llm(llm: str) -> BaseChatModel:
    """Import chat llm from llm name"""
    from bisheng.interface.llms.base import llm_creator
    if llm in llm_creator.type_to_loader_dict:
        return llm_creator.type_to_loader_dict[llm]
    return import_class(f'bisheng_langchain.chat_models.{llm}')


def import_chain_contribute_llm(llm: str) -> BaseChatModel:
    """Import chat llm from llm name"""
    from bisheng.interface.llms.base import llm_creator
    if llm in llm_creator.type_to_loader_dict:
        return llm_creator.type_to_loader_dict[llm]
    return import_class(f'bisheng_langchain.chat_models.{llm}')


def import_retriever(retriever: str) -> Any:
    """Import retriever from retriever name"""
    from bisheng.interface.retrievers.base import retriever_creator
    if retriever in retriever_creator.type_to_loader_dict:
        return retriever_creator.type_to_loader_dict[retriever]

    return import_module(f'from langchain_community.retrievers import {retriever}')


def import_autogenRoles(autogen: str) -> Any:
    return import_module(f'from bisheng_langchain.autogen_role import {autogen}')


def import_memory(memory: str) -> Any:
    """Import memory from memory name"""
    from bisheng.interface.memories.base import memory_creator
    if memory in memory_creator.type_to_loader_dict:
        return memory_creator.type_to_loader_dict[memory]
    return import_module(f'from langchain.memory import {memory}')


def import_class(class_path: str) -> Any:
    """Import class from class path"""
    module_path, class_name = class_path.rsplit('.', 1)
    module = import_module(module_path)
    return getattr(module, class_name)


def import_prompt(prompt: str) -> Type[PromptTemplate]:
    """Import prompt from prompt name"""
    from bisheng.interface.prompts.base import prompt_creator

    if prompt in prompt_creator.type_to_loader_dict:
        return prompt_creator.type_to_loader_dict[prompt]

    return import_class(f'langchain.prompts.{prompt}')


def import_wrapper(wrapper: str) -> Any:
    """Import wrapper from wrapper name"""
    if wrapper in wrapper_creator.type_to_loader_dict:
        return wrapper_creator.type_to_loader_dict[wrapper]


def import_toolkit(toolkit: str) -> Any:
    """Import toolkit from toolkit name"""
    from bisheng.interface.toolkits.base import toolkits_creator
    return toolkits_creator.type_to_loader_dict[toolkit]


def import_agent(agent: str) -> Agent:
    """Import agent from agent name"""
    # check for custom agent
    from bisheng_langchain import agents
    if agent in agents.__all__:
        return import_class(f'bisheng_langchain.agents.{agent}')
    return import_class(f'langchain.agents.{agent}')


def import_llm(llm: str) -> BaseLanguageModel:
    """Import llm from llm name"""
    from bisheng.interface.llms.base import llm_creator
    return next(x for x in llm_creator.type_to_loader_dict.values() if x.__name__ == llm)


def import_tool(tool: str) -> BaseTool:
    """Import tool from tool name"""
    from bisheng.interface.tools.base import tool_creator

    if tool in tool_creator.type_to_loader_dict:
        return tool_creator.type_to_loader_dict[tool]['fcn']

    return import_class(f'langchain_community.tools.{tool}')


def import_chain(chain: str) -> Type[Chain]:
    """Import chain from chain name"""
    from bisheng.interface.chains.base import chain_creator
    return next(x for x in chain_creator.type_to_loader_dict.values() if x.__name__ == chain)


def import_embedding(embedding: str) -> Any:
    """Import embedding from embedding name"""
    from bisheng.interface.embeddings.base import embedding_creator
    return next(x for x in embedding_creator.type_to_loader_dict.values()
                if x.__name__ == embedding)


def import_vectorstore(vectorstore: str) -> Any:
    """Import vectorstore from vectorstore name"""
    from bisheng_langchain import vectorstores
    from bisheng.interface.vector_store.base import vectorstore_creator
    if vectorstore_creator.type_to_loader_dict.get(vectorstore) is not None:
        return vectorstore_creator.type_to_loader_dict[vectorstore]
    if vectorstore in vectorstores.__all__:
        return import_class(f'bisheng_langchain.vectorstores.{vectorstore}')
    return import_class(f'langchain_community.vectorstores.{vectorstore}')


def import_documentloader(documentloader: str) -> Any:
    """Import documentloader from documentloader name"""
    from bisheng_langchain import document_loaders
    from bisheng.interface.document_loaders.base import documentloader_creator

    if documentloader in document_loaders.__all__:
        return import_class(f'bisheng_langchain.document_loaders.{documentloader}')
    return next(x for x in documentloader_creator.type_to_loader_dict.values()
                if x.__name__ == documentloader)


def import_textsplitter(textsplitter: str) -> Any:
    """Import textsplitter from textsplitter name"""
    return import_class(f'langchain.text_splitter.{textsplitter}')


def import_utility(utility: str) -> Any:
    """Import utility from utility name"""
    if utility == 'SQLDatabase':
        return import_class(f'langchain.sql_database.{utility}')
    return import_class(f'langchain_community.utilities.{utility}')


def get_function(code):
    """Get the function"""
    function_name = validate.extract_function_name(code)

    return validate.create_function(code, function_name)


def eval_custom_component_code(code: str) -> Type[CustomComponent]:
    """Evaluate custom component code"""
    class_name = validate.extract_class_name(code)
    return validate.create_class(code, class_name)
