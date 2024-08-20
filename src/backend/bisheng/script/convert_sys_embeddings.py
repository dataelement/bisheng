from bisheng.database.models.knowledge import KnowledgeDao
from bisheng.database.models.llm_server import LLMServer, LLMServerType, LLMModelType, LLMModel, LLMDao
from bisheng.settings import settings


def parse_openai_embedding_conf(name, model_name, embedding_conf):
    # 说明是azure的api服务
    if embedding_conf.get('openai_api_type') in ('azure', 'azure_ad', 'azuread'):
        server = LLMServer(
            name=f"AzureOpenAI",
            description='系统升级自动添加',
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
            description='系统升级自动添加',
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
        description='系统升级自动添加',
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


# 将系统配置里的embedding配置项，转为模型管理里的服务提供方, 升级034执行此脚本
def convert_sys_embeddings_to_mysql():
    knowledge_conf = settings.get_knowledge()
    embeddings = knowledge_conf.get('embeddings', {})
    if not embeddings:
        print('no found embeddings')
        return
    # 查询是否有已存在的知识库
    all_knowledge = KnowledgeDao.get_all_knowledge()
    if not all_knowledge:
        return

    # 先将系统配置全部入库
    need_add_server = {}
    need_add_server_index = {}
    for name, embedding_conf in embeddings.items():
        model_name = embedding_conf.get('model')
        if not model_name and name == 'text-embedding-ada-002':
            model_name = 'text-embedding-ada-002'

        if not model_name:
            print("未找到model名字，不插入到模型管理内")
            continue
        # 说明是openai的官方服务
        if name == 'text-embedding-ada-002' or embedding_conf.get('component') == 'openai':
            server, model = parse_openai_embedding_conf(name, model_name, embedding_conf)
        else:
            # 说明是rt部署的embedding模型
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

    # 重新设置知识库的模型配置
    update_knowledge = []
    for one in all_knowledge:
        if one.model in need_add_server:
            print(f"修改知识库【{one.name}】 的模型配置")
            one.model = need_add_server[one.model].id
            update_knowledge.append(one)

    if update_knowledge:
        KnowledgeDao.update_knowledge_list(update_knowledge)

    if not need_add_server_index.get(LLMServerType.BISHENG_RT.value):
        # 添加一个默认的RT服务提供方
        server = LLMServer(
            name=f"RT_OLD",
            description='系统升级自动添加，后续不建议使用',
            type=LLMServerType.BISHENG_RT.value,
            config={
                "host_base_url": 'http://xxxx:8000',
            },
            user_id=1,
        )
        llm_server = LLMDao.insert_server_with_models(server, [])


if __name__ == '__main__':
    convert_sys_embeddings_to_mysql()
