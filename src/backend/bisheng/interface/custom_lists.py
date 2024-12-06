import inspect
from typing import Any

from bisheng.interface.agents.custom import CUSTOM_AGENTS
from bisheng.interface.chains.custom import CUSTOM_CHAINS
from bisheng.interface.embeddings.custom import CUSTOM_EMBEDDING
from bisheng.interface.importing.utils import import_class
from bisheng_langchain import chat_models
from bisheng_langchain import document_loaders as contribute_loader
from bisheng_langchain import embeddings as contribute_embeddings
from langchain import llms, memory, text_splitter
from langchain_community.utilities import requests
from langchain_anthropic import ChatAnthropic
from langchain_community import agent_toolkits, document_loaders, embeddings
from langchain_community.chat_models import ChatVertexAI, MiniMaxChat, ChatOllama
from langchain_openai import AzureChatOpenAI, ChatOpenAI, OpenAIEmbeddings, AzureOpenAIEmbeddings, OpenAI

# LLMs
llm_type_to_cls_dict = {}
for k, v in llms.get_type_to_cls_dict().items():
    try:
        llm_type_to_cls_dict[k] = v()
    except Exception:
        pass
llm_type_to_cls_dict['ChatAnthropic'] = ChatAnthropic  # type: ignore
llm_type_to_cls_dict['AzureChatOpenAI'] = AzureChatOpenAI  # type: ignore
llm_type_to_cls_dict['ChatOpenAI'] = ChatOpenAI  # type: ignore
llm_type_to_cls_dict['ChatVertexAI'] = ChatVertexAI  # type: ignore
llm_type_to_cls_dict['MiniMaxChat'] = MiniMaxChat
llm_type_to_cls_dict['ChatOllama'] = ChatOllama
llm_type_to_cls_dict["OpenAI"] = OpenAI

# llm contribute
llm_type_to_cls_dict.update({
    llm_name: import_class(f'bisheng_langchain.chat_models.{llm_name}')
    for llm_name in chat_models.__all__
})

# Toolkits
toolkit_type_to_loader_dict: dict[str, Any] = {
    toolkit_name: import_class(f'langchain_community.agent_toolkits.{toolkit_name}')
    # if toolkit_name is lower case it is a loader
    for toolkit_name in agent_toolkits.__all__ if toolkit_name.islower()
}

toolkit_type_to_cls_dict: dict[str, Any] = {
    toolkit_name: import_class(f'langchain_community.agent_toolkits.{toolkit_name}')
    # if toolkit_name is not lower case it is a class
    for toolkit_name in agent_toolkits.__all__ if not toolkit_name.islower()
}

# Memories
memory_type_to_cls_dict: dict[str, Any] = {}
for memory_name in memory.__all__:
    if memory_name.find("ChatMessageHistory") != -1:
        memory_type_to_cls_dict[memory_name] = import_class(f"langchain_community.chat_message_histories.{memory_name}")
    elif memory_name == "ConversationKGMemory":
        memory_type_to_cls_dict[memory_name] = import_class(f"langchain_community.memory.kg.{memory_name}")
    elif memory_name == "MotorheadMemory":
        memory_type_to_cls_dict[memory_name] = import_class(f"langchain_community.memory.motorhead_memory.{memory_name}")
    elif memory_name == "ZepMemory":
        memory_type_to_cls_dict[memory_name] = import_class(f"langchain_community.memory.zep_memory.{memory_name}")
    else:
        memory_type_to_cls_dict[memory_name] = import_class(f'langchain.memory.{memory_name}')


# Wrappers
wrapper_type_to_cls_dict: dict[str, Any] = {
    wrapper.__name__: wrapper
    for wrapper in [requests.RequestsWrapper]
}

# Embeddings
embedding_type_to_cls_dict: dict[str, Any] = {
    embedding_name: import_class(f'langchain_community.embeddings.{embedding_name}')
    for embedding_name in embeddings.__all__
}

embedding_type_to_cls_dict.update({
    embedding_name:
        import_class(f'bisheng_langchain.embeddings.{embedding_name}')
    for embedding_name in contribute_embeddings.__all__
})
embedding_type_to_cls_dict.update({
    "OpenAIEmbeddings": OpenAIEmbeddings,
    "AzureOpenAIEmbeddings": AzureOpenAIEmbeddings,
})

# Document Loaders
documentloaders_type_to_cls_dict: dict[str, Any] = {
    documentloader_name:
        import_class(f'langchain_community.document_loaders.{documentloader_name}')
    for documentloader_name in document_loaders.__all__
}

# contribute
documentloaders_type_to_cls_dict.update({
    loader:
        import_class(f'bisheng_langchain.document_loaders.{loader}')
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
}  # type: ignore
