from typing import Dict, Type

from bisheng.graph.vertex import types
from bisheng.graph.vertex.base import Vertex
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

VERTEX_TYPE_MAP: Dict[str, Type[Vertex]] = {
    **{t: types.PromptVertex for t in prompt_creator.to_list()},
    **{t: types.AgentVertex for t in agent_creator.to_list()},
    **{t: types.ChainVertex for t in chain_creator.to_list()},
    **{t: types.ToolVertex for t in tool_creator.to_list()},
    **{t: types.ToolkitVertex for t in toolkits_creator.to_list()},
    **{t: types.WrapperVertex for t in wrapper_creator.to_list()},
    **{t: types.LLMVertex for t in llm_creator.to_list()},
    **{t: types.MemoryVertex for t in memory_creator.to_list()},
    **{t: types.EmbeddingVertex for t in embedding_creator.to_list()},
    **{t: types.VectorStoreVertex for t in vectorstore_creator.to_list()},
    **{t: types.DocumentLoaderVertex for t in documentloader_creator.to_list()},
    **{t: types.TextSplitterVertex for t in textsplitter_creator.to_list()},
    **{t: types.OutputParserVertex for t in output_parser_creator.to_list()},
    **{t: types.RetrieverVertex for t in retriever_creator.to_list()},
}
