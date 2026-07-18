from bisheng.common.services.config_service import settings
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.llm.domain.const import LLMServerType, LLMModelType
from bisheng.llm.domain.models import LLMServer, LLMDao, LLMModel


def parse_openai_embedding_conf(name, model_name, embedding_conf):
    # Explanation isazureright of privacyapiSERVICES
    if embedding_conf.get('openai_api_type') in ('azure', 'azure_ad', 'azuread'):
        server = LLMServer(
            name=f"AzureOpenAI",
            description='System upgrade automatically added',
            type=LLMServerType.AZURE_OPENAI.value,
            config={
                "azure_endpoint": embedding_conf.pop("azure_endpoint", ''),
                "openai_api_key": embedding_conf.pop("openai_api_key", ''),
                "openai_api_version": embedding_conf.pop("openai_api_version", '')
            },
            user_id=1,
        )
        model = LLMModel(
            name=name,
            model_name=model_name,
            model_type=LLMModelType.EMBEDDING.value,
            online=True,
            user_id=1,
        )
    else:
        server = LLMServer(
            name=f"OpenAI",
            description='System upgrade automatically added',
            type=LLMServerType.OPENAI.value,
            config={
                "openai_api_key": embedding_conf.pop("openai_api_key", ''),
                "openai_api_base": embedding_conf.pop("openai_api_base", ''),
                "openai_proxy": embedding_conf.pop("openai_proxy", ''),
            },
            user_id=1,
        )
        model = LLMModel(
            name=name,
            model_name=model_name,
            model_type=LLMModelType.EMBEDDING.value,
            online=True,
            user_id=1,
        )
    return server, model


def parse_rt_embedding_conf(name, model_name, embedding_conf):
    server = LLMServer(
        name=f"RT",
        description='System upgrade automatically added',
        type=LLMServerType.BISHENG_RT.value,
        config={
            "host_base_url": embedding_conf.get("host_base_url", ''),
        },
        user_id=1,
    )
    model = LLMModel(
        name=name,
        model_name=model_name,
        model_type=LLMModelType.EMBEDDING.value,
        online=True,
        user_id=1,
    )
    return server, model


# In the system configuration,embeddingconfiguration item, to the service provider in the model management, level-up034Execute this script
def convert_sys_embeddings_to_mysql():
    knowledge_conf = settings.get_knowledge()
    embeddings = knowledge_conf.get('embeddings', {})
    if not embeddings:
        print('no found embeddings')
        return
    # Query if there is an existing knowledge base
    all_knowledge = KnowledgeDao.get_all_knowledge()
    if not all_knowledge:
        return

    # Warehousing all system configurations first
    need_add_server = {}
    need_add_server_index = {}
    for name, embedding_conf in embeddings.items():
        model_name = embedding_conf.get('model')
        if not model_name and name == 'text-embedding-ada-002':
            model_name = 'text-embedding-ada-002'

        if not model_name:
            print("not foundmodelFirst name, not inserted into model management")
            continue
        # Explanation isopenaiOfficial Services of
        if name == 'text-embedding-ada-002' or embedding_conf.get('component') == 'openai':
            server, model = parse_openai_embedding_conf(name, model_name, embedding_conf)
        else:
            # Explanation isrtDeployedembeddingModels
            server, model = parse_rt_embedding_conf(name, model_name, embedding_conf)
        if server.type not in need_add_server_index:
            need_add_server_index[server.type] = 0
        need_add_server_index[server.type] += 1
        server.name = f"{server.name}_{need_add_server_index[server.type]}"

        llm_server = LLMDao.insert_server_with_models(server, [model])
        llm_model_list = LLMDao.get_model_by_server_ids([llm_server.id])
        for one in llm_model_list:
            if one.name == name:
                need_add_server[name] = one

    # Reset Model Configuration for Knowledge Base
    update_knowledge = []
    for one in all_knowledge:
        if one.model in need_add_server:
            print(f"Modify Knowledge Base【{one.name}】 Model Configuration for")
            one.model = need_add_server[one.model].id
            update_knowledge.append(one)

    if update_knowledge:
        KnowledgeDao.update_knowledge_list(update_knowledge)

    if not need_add_server_index.get(LLMServerType.BISHENG_RT.value):
        # Add a defaultRTservice provider
        server = LLMServer(
            name=f"RT_OLD",
            description='The system upgrade is automatically added, and it is not recommended to use it in the future',
            type=LLMServerType.BISHENG_RT.value,
            config={
                "host_base_url": 'http://xxxx:8000',
            },
            user_id=1,
        )
        llm_server = LLMDao.insert_server_with_models(server, [])


if __name__ == '__main__':
    convert_sys_embeddings_to_mysql()
