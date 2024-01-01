import json
import os
from typing import Any, Callable, Dict, Type

from bisheng.database.base import session_getter
from bisheng.database.models.knowledge import Knowledge
from bisheng.settings import settings
from bisheng_langchain.embeddings.host_embedding import HostEmbeddings
from bisheng_langchain.vectorstores import ElasticKeywordsSearch
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.vectorstores import (FAISS, Chroma, Milvus, MongoDBAtlasVectorSearch, Pinecone,
                                    Qdrant, SupabaseVectorStore, Weaviate)
from sqlmodel import select


def docs_in_params(params: dict) -> bool:
    """Check if params has documents OR texts and one of them is not an empty list,
    If any of them is not an empty list, return True, else return False"""
    return ('documents' in params and params['documents']) or ('texts' in params
                                                               and params['texts'])


def initialize_mongodb(class_object: Type[MongoDBAtlasVectorSearch], params: dict, search: dict):
    """Initialize mongodb and return the class object"""

    MONGODB_ATLAS_CLUSTER_URI = params.pop('mongodb_atlas_cluster_uri')
    if not MONGODB_ATLAS_CLUSTER_URI:
        raise ValueError('Mongodb atlas cluster uri must be provided in the params')
    from pymongo import MongoClient
    import certifi

    client: MongoClient = MongoClient(MONGODB_ATLAS_CLUSTER_URI, tlsCAFile=certifi.where())
    db_name = params.pop('db_name', None)
    collection_name = params.pop('collection_name', None)
    if not db_name or not collection_name:
        raise ValueError('db_name and collection_name must be provided in the params')

    index_name = params.pop('index_name', None)
    if not index_name:
        raise ValueError('index_name must be provided in the params')

    collection = client[db_name][collection_name]
    if not docs_in_params(params):
        # __init__ requires collection, embedding and index_name
        init_args = {
            'collection': collection,
            'index_name': index_name,
            'embedding': params.get('embedding'),
        }

        return class_object(**init_args)

    if 'texts' in params:
        params['documents'] = params.pop('texts')

    params['collection'] = collection
    params['index_name'] = index_name

    return class_object.from_documents(**params)


def initialize_supabase(class_object: Type[SupabaseVectorStore], params: dict, search: dict):
    """Initialize supabase and return the class object"""
    from supabase.client import Client, create_client

    if 'supabase_url' not in params or 'supabase_service_key' not in params:
        raise ValueError('Supabase url and service key must be provided in the params')
    if 'texts' in params:
        params['documents'] = params.pop('texts')

    client_kwargs = {
        'supabase_url': params.pop('supabase_url'),
        'supabase_key': params.pop('supabase_service_key'),
    }

    supabase: Client = create_client(**client_kwargs)
    if not docs_in_params(params):
        params.pop('documents', None)
        params.pop('texts', None)
        return class_object(client=supabase, **params)
    # If there are docs in the params, create a new index

    return class_object.from_documents(client=supabase, **params)


def initialize_weaviate(class_object: Type[Weaviate], params: dict, search: dict):
    """Initialize weaviate and return the class object"""
    if not docs_in_params(params):
        import weaviate  # type: ignore

        client_kwargs_json = params.get('client_kwargs', '{}')
        client_kwargs = json.loads(client_kwargs_json)
        client_params = {
            'url': params.get('weaviate_url'),
        }
        client_params.update(client_kwargs)
        weaviate_client = weaviate.Client(**client_params)

        new_params = {
            'client': weaviate_client,
            'index_name': params.get('index_name'),
            'text_key': params.get('text_key'),
        }
        return class_object(**new_params)
    # If there are docs in the params, create a new index
    if 'texts' in params:
        params['documents'] = params.pop('texts')

    return class_object.from_documents(**params)


def initialize_faiss(class_object: Type[FAISS], params: dict, search: dict):
    """Initialize faiss and return the class object"""

    if not docs_in_params(params):
        return class_object.load_local

    save_local = params.get('save_local')
    faiss_index = class_object(**params)
    if save_local:
        faiss_index.save_local(folder_path=save_local)
    return faiss_index


def initialize_pinecone(class_object: Type[Pinecone], params: dict, search: dict):
    """Initialize pinecone and return the class object"""

    import pinecone  # type: ignore

    pinecone_api_key = params.get('pinecone_api_key')
    pinecone_env = params.get('pinecone_env')

    if pinecone_api_key is None or pinecone_env is None:
        if os.getenv('PINECONE_API_KEY') is not None:
            pinecone_api_key = os.getenv('PINECONE_API_KEY')
        if os.getenv('PINECONE_ENV') is not None:
            pinecone_env = os.getenv('PINECONE_ENV')

    if pinecone_api_key is None or pinecone_env is None:
        raise ValueError('Pinecone API key and environment must be provided in the params')

    # initialize pinecone
    pinecone.init(
        api_key=pinecone_api_key,  # find at app.pinecone.io
        environment=pinecone_env,  # next to api key in console
    )

    # If there are no docs in the params, return an existing index
    # but first remove any texts or docs keys from the params
    if not docs_in_params(params):
        existing_index_params = {
            'embedding': params.pop('embedding'),
        }
        if 'index_name' in params:
            existing_index_params['index_name'] = params.pop('index_name')
        if 'namespace' in params:
            existing_index_params['namespace'] = params.pop('namespace')

        return class_object.from_existing_index(**existing_index_params)
    # If there are docs in the params, create a new index
    if 'texts' in params:
        params['documents'] = params.pop('texts')
    return class_object.from_documents(**params)


def initialize_chroma(class_object: Type[Chroma], params: dict, search: dict):
    """Initialize a ChromaDB object from the params"""
    persist = params.pop('persist', False)
    if not docs_in_params(params):
        params.pop('documents', None)
        params.pop('texts', None)
        params['embedding_function'] = params.pop('embedding')
        chromadb = class_object(**params)
    else:
        if 'texts' in params:
            params['documents'] = params.pop('texts')
        for doc in params['documents']:
            if doc.metadata is None:
                doc.metadata = {}
            for key, value in doc.metadata.items():
                if value is None:
                    doc.metadata[key] = ''
        chromadb = class_object.from_documents(**params)
    if persist:
        chromadb.persist()
    return chromadb


def initialize_qdrant(class_object: Type[Qdrant], params: dict, search: dict):
    if not docs_in_params(params):
        if 'location' not in params and 'api_key' not in params:
            raise ValueError('Location and API key must be provided in the params')
        from qdrant_client import QdrantClient

        client_params = {
            'location': params.pop('location'),
            'api_key': params.pop('api_key'),
        }
        lc_params = {
            'collection_name': params.pop('collection_name'),
            'embeddings': params.pop('embedding'),
        }
        client = QdrantClient(**client_params)

        return class_object(client=client, **lc_params)

    return class_object.from_documents(**params)


def initial_milvus(class_object: Type[Milvus], params: dict, search_kwargs: dict):
    if not params.get('connection_args') and settings.get_knowledge().get('vectorstores').get(
            'Milvus'):
        params['connection_args'] = settings.get_knowledge().get('vectorstores').get('Milvus').get(
            'connection_args')
    elif isinstance(params.get('connection_args'), str):
        print(f"milvus before params={params} type={type(params['connection_args'])}")
        params['connection_args'] = eval(params.pop('connection_args'))
    if 'embedding' not in params:
        # 匹配知识库的embedding
        col = params['collection_name']
        collection_id = params.pop('collection_id', '')
        with session_getter() as session:
            if collection_id:
                knowledge = session.get(Knowledge, collection_id)
                params['collection_name'] = knowledge.collection_name
            else:
                knowledge = session.exec(
                    select(Knowledge).where(Knowledge.collection_name == col)).first()

        if not knowledge:
            raise Exception(f'不能找到知识库collection={col}')
        model_param = settings.get_knowledge().get('embeddings').get(knowledge.model)
        if knowledge.model == 'text-embedding-ada-002':
            embedding = OpenAIEmbeddings(**model_param)
        else:
            embedding = HostEmbeddings(**model_param)
        params['embedding'] = embedding
        if knowledge.collection_name.startswith('partition'):
            search_kwargs.update({'partition_key': knowledge.id})
    return class_object.from_documents(**params)


def initial_elastic(class_object: Type[ElasticKeywordsSearch], params: dict, search: dict):
    if not params.get('elasticsearch_url') and settings.get_knowledge().get('vectorstores').get(
            'ElasticKeywordsSearch'):
        params['elasticsearch_url'] = settings.get_knowledge().get('vectorstores').get(
            'ElasticKeywordsSearch').get('elasticsearch_url')

    if not params.get('ssl_verify') and settings.get_knowledge().get('vectorstores').get(
            'ElasticKeywordsSearch'):
        params['ssl_verify'] = eval(settings.get_knowledge().get('vectorstores').get(
            'ElasticKeywordsSearch').get('ssl_verify'))
    elif isinstance(params.get('ssl_verify'), str):
        params['ssl_verify'] = eval(params['ssl_verify'])

    collection_id = params.pop('collection_id', '')
    if collection_id:
        with session_getter() as session:
            knowledge = session.get(Knowledge, collection_id)
        index_name = knowledge.index_name or knowledge.collection_name
        params['index_name'] = index_name
    params['embedding'] = ''
    return class_object.from_documents(**params)


vecstore_initializer: Dict[str, Callable[[Type[Any], dict], Any]] = {
    'Pinecone': initialize_pinecone,
    'Chroma': initialize_chroma,
    'Qdrant': initialize_qdrant,
    'Weaviate': initialize_weaviate,
    'FAISS': initialize_faiss,
    'Milvus': initial_milvus,
    'ElasticVectorSearch': initial_elastic,
    'ElasticKeywordsSearch': initial_elastic,
    'SupabaseVectorStore': initialize_supabase,
    'MongoDBAtlasVectorSearch': initialize_mongodb,
}
