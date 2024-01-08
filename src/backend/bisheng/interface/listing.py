from bisheng.utils.lazy_load import LazyLoadDictBase

# from bisheng.interface.agents.base import agent_creator
# from bisheng.interface.autogenRole.base import autogenrole_creator
# from bisheng.interface.chains.base import chain_creator
# from bisheng.interface.document_loaders.base import documentloader_creator
# from bisheng.interface.embeddings.base import embedding_creator
# from bisheng.interface.inputoutput.base import input_output_creator
# from bisheng.interface.llms.base import llm_creator
# from bisheng.interface.memories.base import memory_creator
# from bisheng.interface.output_parsers.base import output_parser_creator
# from bisheng.interface.prompts.base import prompt_creator
# from bisheng.interface.retrievers.base import retriever_creator
# from bisheng.interface.text_splitters.base import textsplitter_creator
# from bisheng.interface.toolkits.base import toolkits_creator
# from bisheng.interface.tools.base import tool_creator
# from bisheng.interface.utilities.base import utility_creator
# from bisheng.interface.vector_store.base import vectorstore_creator
# from bisheng.interface.wrappers.base import wrapper_creator

# def get_type_dict():
#     return {
#         'agents': agent_creator.to_list(),
#         'prompts': prompt_creator.to_list(),
#         'llms': llm_creator.to_list(),
#         'tools': tool_creator.to_list(),
#         'chains': chain_creator.to_list(),
#         'memory': memory_creator.to_list(),
#         'toolkits': toolkits_creator.to_list(),
#         'wrappers': wrapper_creator.to_list(),
#         'documentLoaders': documentloader_creator.to_list(),
#         'vectorStore': vectorstore_creator.to_list(),
#         'embeddings': embedding_creator.to_list(),
#         'textSplitters': textsplitter_creator.to_list(),
#         'utilities': utility_creator.to_list(),
#         'outputParsers': output_parser_creator.to_list(),
#         'retrievers': retriever_creator.to_list(),
#         'inputOutput': input_output_creator.to_list(),
#         'autogenRoles': autogenrole_creator.to_list(),
#     }

# LANGCHAIN_TYPES_DICT = get_type_dict()

# # Now we'll build a dict with Langchain types and ours

# ALL_TYPES_DICT = {
#     **LANGCHAIN_TYPES_DICT,
#     'Custom': ['Custom Tool', 'Python Function'],
# }


class AllTypesDict(LazyLoadDictBase):

    def __init__(self):
        self._all_types_dict = None

    @property
    def ALL_TYPES_DICT(self):
        return self.all_types_dict

    def _build_dict(self):
        langchain_types_dict = self.get_type_dict()
        return {
            **langchain_types_dict,
            'Custom': ['Custom Tool', 'Python Function'],
        }

    def get_type_dict(self):
        from bisheng.interface.types import get_all_types_dict

        return get_all_types_dict()


lazy_load_dict = AllTypesDict()
