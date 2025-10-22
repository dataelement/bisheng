from langchain_community.embeddings import DashScopeEmbeddings
from langchain_ollama import OllamaEmbeddings
from langchain_openai import OpenAIEmbeddings, AzureOpenAIEmbeddings

__all__ = [
    'OllamaEmbeddings',
    'OpenAIEmbeddings',
    'AzureOpenAIEmbeddings',
    'DashScopeEmbeddings',

]
