import inspect
from typing import Any

from bisheng.interface.agents.custom import CUSTOM_AGENTS
from bisheng.interface.chains.custom import CUSTOM_CHAINS
from bisheng.interface.embeddings.custom import CUSTOM_EMBEDDING
from bisheng.interface.importing.utils import import_class
from bisheng.interface.inputoutput.custom import CUSTOM_INPUTOUTPUT
from bisheng_langchain import chat_models
from bisheng_langchain import document_loaders as contribute_loader
from bisheng_langchain import embeddings as contribute_embeddings
from langchain import document_loaders, embeddings, llms, memory, requests, text_splitter
from langchain.agents import agent_toolkits
from langchain.chat_models import AzureChatOpenAI, ChatAnthropic, ChatOpenAI, ChatVertexAI

# LLMs
llm_type_to_cls_dict = llms.type_to_cls_dict
llm_type_to_cls_dict['anthropic-chat'] = ChatAnthropic  # type: ignore
llm_type_to_cls_dict['azure-chat'] = AzureChatOpenAI  # type: ignore
llm_type_to_cls_dict['openai-chat'] = ChatOpenAI  # type: ignore
llm_type_to_cls_dict['vertexai-chat'] = ChatVertexAI  # type: ignore

# llm contribute
llm_type_to_cls_dict.update({
    llm_name: import_class(f'bisheng_langchain.chat_models.{llm_name}')
    for llm_name in chat_models.__all__
})

# Toolkits
toolkit_type_to_loader_dict: dict[str, Any] = {
    toolkit_name: import_class(f'langchain.agents.agent_toolkits.{toolkit_name}')
    # if toolkit_name is lower case it is a loader
    for toolkit_name in agent_toolkits.__all__
    if toolkit_name.islower()
}

toolkit_type_to_cls_dict: dict[str, Any] = {
    toolkit_name: import_class(f'langchain.agents.agent_toolkits.{toolkit_name}')
    # if toolkit_name is not lower case it is a class
    for toolkit_name in agent_toolkits.__all__
    if not toolkit_name.islower()
}

# Memories
memory_type_to_cls_dict: dict[str, Any] = {
    memory_name: import_class(f'langchain.memory.{memory_name}') for memory_name in memory.__all__
}

# Wrappers
wrapper_type_to_cls_dict: dict[str, Any] = {
    wrapper.__name__: wrapper for wrapper in [requests.RequestsWrapper]
}

# Embeddings
embedding_type_to_cls_dict: dict[str, Any] = {
    embedding_name: import_class(f'langchain.embeddings.{embedding_name}')
    for embedding_name in embeddings.__all__
}

embedding_type_to_cls_dict.update({
    embedding_name: import_class(f'bisheng_langchain.embeddings.{embedding_name}')
    for embedding_name in contribute_embeddings.__all__
})

# Document Loaders
documentloaders_type_to_cls_dict: dict[str, Any] = {
    documentloader_name: import_class(f'langchain.document_loaders.{documentloader_name}')
    for documentloader_name in document_loaders.__all__
}

# contribute
documentloaders_type_to_cls_dict.update({
    loader: import_class(f'bisheng_langchain.document_loaders.{loader}')
    for loader in contribute_loader.__all__
})

# Text Splitters
textsplitter_type_to_cls_dict: dict[str,
                                    Any] = dict(inspect.getmembers(text_splitter, inspect.isclass))

# merge CUSTOM_AGENTS and CUSTOM_CHAINS
CUSTOM_NODES = {
    **CUSTOM_AGENTS,
    **CUSTOM_CHAINS,
    **CUSTOM_EMBEDDING,
    **CUSTOM_INPUTOUTPUT
}  # type: ignore
