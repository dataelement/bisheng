from bisheng.graph.vertex import types
from bisheng.interface.agents.base import agent_creator
from bisheng.interface.chains.base import chain_creator
from bisheng.interface.document_loaders.base import documentloader_creator
from bisheng.interface.embeddings.base import embedding_creator
from bisheng.interface.llms.base import llm_creator
from bisheng.interface.memories.base import memory_creator
from bisheng.interface.output_parsers.base import output_parser_creator
from bisheng.interface.prompts.base import prompt_creator
from bisheng.interface.retrievers.base import retriever_creator
from bisheng.interface.text_splitters.base import textsplitter_creator
from bisheng.interface.toolkits.base import toolkits_creator
from bisheng.interface.tools.base import tool_creator
from bisheng.interface.vector_store.base import vectorstore_creator
from bisheng.interface.wrappers.base import wrapper_creator
from bisheng.utils.lazy_load import LazyLoadDictBase


class VertexTypesDict(LazyLoadDictBase):

    def __init__(self):
        self._all_types_dict = None

    @property
    def VERTEX_TYPE_MAP(self):
        return self.all_types_dict

    def _build_dict(self):
        langchain_types_dict = self.get_type_dict()
        return {
            **langchain_types_dict,
            'Custom': ['Custom Tool', 'Python Function'],
        }

    def get_custom_component_vertex_type(self):
        return types.CustomComponentVertex

    def get_type_dict(self):
        return {
            **{
                t: types.PromptVertex
                for t in prompt_creator.to_list()
            },
            **{
                t: types.AgentVertex
                for t in agent_creator.to_list()
            },
            **{
                t: types.ChainVertex
                for t in chain_creator.to_list()
            },
            **{
                t: types.ToolVertex
                for t in tool_creator.to_list()
            },
            **{
                t: types.ToolkitVertex
                for t in toolkits_creator.to_list()
            },
            **{
                t: types.WrapperVertex
                for t in wrapper_creator.to_list()
            },
            **{
                t: types.LLMVertex
                for t in llm_creator.to_list()
            },
            **{
                t: types.MemoryVertex
                for t in memory_creator.to_list()
            },
            **{
                t: types.EmbeddingVertex
                for t in embedding_creator.to_list()
            },
            **{
                t: types.VectorStoreVertex
                for t in vectorstore_creator.to_list()
            },
            **{
                t: types.DocumentLoaderVertex
                for t in documentloader_creator.to_list()
            },
            **{
                t: types.TextSplitterVertex
                for t in textsplitter_creator.to_list()
            },
            **{
                t: types.OutputParserVertex
                for t in output_parser_creator.to_list()
            },
            # **{t: types.CustomComponentVertex for t in custom_component_creator.to_list()},
            **{
                t: types.RetrieverVertex
                for t in retriever_creator.to_list()
            },
        }


lazy_load_vertex_dict = VertexTypesDict()
