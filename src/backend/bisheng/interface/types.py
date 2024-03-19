from bisheng.interface.agents.base import agent_creator
from bisheng.interface.autogenRole.base import autogenrole_creator
from bisheng.interface.chains.base import chain_creator
from bisheng.interface.document_loaders.base import documentloader_creator
from bisheng.interface.embeddings.base import embedding_creator
from bisheng.interface.inputoutput.base import input_output_creator
from bisheng.interface.llms.base import llm_creator
from bisheng.interface.memories.base import memory_creator
from bisheng.interface.output_parsers.base import output_parser_creator
from bisheng.interface.prompts.base import prompt_creator
from bisheng.interface.retrievers.base import retriever_creator
from bisheng.interface.text_splitters.base import textsplitter_creator
from bisheng.interface.toolkits.base import toolkits_creator
from bisheng.interface.tools.base import tool_creator
from bisheng.interface.utilities.base import utility_creator
from bisheng.interface.vector_store.base import vectorstore_creator
from bisheng.interface.wrappers.base import wrapper_creator
from cachetools import LRUCache, cached


def get_type_list():
    """Get a list of all langchain types"""
    all_types = build_langchain_types_dict()

    # all_types.pop("tools")

    for key, value in all_types.items():
        all_types[key] = [item['template']['_type'] for item in value.values()]

    return all_types


@cached(LRUCache(maxsize=1))
def build_langchain_types_dict():  # sourcery skip: dict-assign-update-to-union
    """Build a dictionary of all langchain types"""

    all_types = {}

    creators = [
        chain_creator,
        agent_creator,
        prompt_creator,
        llm_creator,
        memory_creator,
        tool_creator,
        toolkits_creator,
        wrapper_creator,
        embedding_creator,
        vectorstore_creator,
        documentloader_creator,
        textsplitter_creator,
        utility_creator,
        output_parser_creator,
        retriever_creator,
        input_output_creator,
        autogenrole_creator,
    ]

    all_types = {}
    for creator in creators:
        created_types = creator.to_dict()
        if created_types[creator.type_name].values():
            all_types.update(created_types)
    return all_types


langchain_types_dict = build_langchain_types_dict()


def get_all_types_dict():
    """Get all types dictionary combining native and custom components."""
    native_components = build_langchain_types_dict()
    # custom_components_from_file = build_custom_components(settings_service)
    # return merge_nested_dicts_with_renaming(native_components, custom_components_from_file)
    return native_components
