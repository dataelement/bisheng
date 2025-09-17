from typing import List
from langchain.embeddings.base import Embeddings


def decide_embeddings(model: str) -> Embeddings:
    """ embed method """
    from bisheng.api.services.llm import LLMService

    return LLMService.get_bisheng_embedding(model_id=model)


def create_knowledge_vector_store(knowledge_ids: List[str], user_name: str, check_auth: bool = True):
    """
    创建知识库模式的 vector_store
    
    Args:
        knowledge_ids: 知识库ID列表
        user_name: 用户名
        check_auth: 是否检查权限
    
    Returns:
        vector_store: Milvus向量存储实例
    """   
    # 延迟导入以避免循环导入
    from bisheng.interface.importing.utils import import_vectorstore
    from bisheng.interface.initialize.loading import instantiate_vectorstore
    
    node_type = 'MilvusWithPermissionCheck'
    params = {
        'user_name': user_name,
        'collection_name': [{'key': knowledge_id} for knowledge_id in knowledge_ids],
        '_is_check_auth': check_auth,
        '_include_private': True  # 新增参数，支持包含个人知识库
    }
    
    class_obj = import_vectorstore(node_type)
    
    # 实例化向量存储
    vector_store = instantiate_vectorstore(node_type, class_object=class_obj, params=params)
    
    return vector_store


def create_knowledge_keyword_store(knowledge_ids: List[str], user_name: str, check_auth: bool = True):
    """
    创建知识库模式的 keyword_store (Elasticsearch)
    
    Args:
        knowledge_ids: 知识库ID列表
        user_name: 用户名
        check_auth: 是否检查权限
    
    Returns:
        keyword_store: Elasticsearch关键词存储实例
    """
    # 延迟导入以避免循环导入
    from bisheng.interface.importing.utils import import_vectorstore
    from bisheng.interface.initialize.loading import instantiate_vectorstore
 
    node_type = 'ElasticsearchWithPermissionCheck'
    params = {
        'user_name': user_name,
        'index_name': [{'key': knowledge_id} for knowledge_id in knowledge_ids],
        '_is_check_auth': check_auth,
        '_include_private': True  # 新增参数，支持包含个人知识库
    }
    
    class_obj = import_vectorstore(node_type)
    
    # 实例化关键词存储
    keyword_store = instantiate_vectorstore(node_type, class_object=class_obj, params=params)
    
    return keyword_store