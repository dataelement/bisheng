import json
import uuid
from typing import List, Dict

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from loguru import logger

from bisheng.api.services.knowledge_imp import decide_vectorstores
from bisheng.api.services.llm import LLMService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schema.inspiration_schema import SOPManagementSchema, SOPManagementUpdateSchema
from bisheng.api.v1.schema.linsight_schema import SopRecordRead
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_500, resp_200
from bisheng.core.app_context import app_ctx
from bisheng.database.models.linsight_sop import LinsightSOP, LinsightSOPDao, LinsightSOPRecord
from bisheng.database.models.llm_server import LLMDao, LLMModelType
from bisheng.database.models.user import UserDao
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.interface.llms.custom import BishengLLM
from bisheng.utils import util
from bisheng.utils.embedding import decide_embeddings
from bisheng_langchain.rag.init_retrievers import KeywordRetriever, BaselineVectorRetriever
from bisheng_langchain.retrievers import EnsembleRetriever
from bisheng_langchain.vectorstores import ElasticKeywordsSearch, Milvus


class SOPManageService:
    __doc__ = "灵思SOP管理服务"

    collection_name = "col_linsight_sop"

    @staticmethod
    async def generate_sop_summary(sop_content: str, llm: BishengLLM = None) -> Dict[str, str]:
        """生成SOP摘要"""
        default_summary = {"sop_title": "SOP名称", "sop_description": "SOP描述"}

        try:
            if llm is None:
                workbench_conf = await LLMService.get_workbench_llm()
                llm = BishengLLM(model_id=workbench_conf.task_model.id, temperature=0)
            prompt_service = app_ctx.get_prompt_loader()
            prompt_obj = prompt_service.render_prompt(
                namespace="sop",
                prompt_name="gen_sop_summary",
                sop_detail=sop_content
            )

            prompt = [
                ("system", prompt_obj.prompt.system),
                ("user", prompt_obj.prompt.user)
            ]

            response = await llm.ainvoke(prompt)
            if not response.content:
                return default_summary

            return json.loads(response.content)

        except Exception as e:
            logger.error(f"生成SOP摘要失败: {e}")
            return default_summary

    @staticmethod
    async def add_sop_record(sop_record: LinsightSOPRecord) -> LinsightSOPRecord:
        """
        添加SOP记录
        """
        if not sop_record.description:
            sop_summary = await SOPManageService.generate_sop_summary(sop_record.content, None)
            sop_record.description = sop_summary["sop_description"]

        return await LinsightSOPDao.create_sop_record(sop_record)

    @staticmethod
    async def get_sop_record(keyword: str = None, sort: str = None, page: int = 1, page_size: int = 10) -> \
            (List[SopRecordRead], int):
        """
        根据关键词查询SOP记录
        """
        user_ids = []
        if keyword:
            # 如果有关键词，先获取用户ID列表
            user_ids = await UserDao.afilter_users(user_ids=[], keyword=keyword)
            user_ids = [one.user_id for one in user_ids]

        res = await LinsightSOPDao.filter_sop_record(keyword, user_ids, page, page_size, sort)
        count = await LinsightSOPDao.count_sop_record(keyword, user_ids)
        if not res:
            return [], 0

        all_users = await UserDao.afilter_users(user_ids=[one.user_id for one in res])
        all_users = {
            one.user_id: one.user_name for one in all_users
        }

        result = []
        for one in res:
            new_one = SopRecordRead.model_validate(one)
            new_one.user_name = all_users.get(one.user_id, str(one.user_id))
            result.append(new_one)
        return result, count

    @staticmethod
    async def update_sop_record_score(session_version_id: str, score: int) -> None:
        await LinsightSOPDao.update_sop_record_score(session_version_id, score)

    @staticmethod
    async def sync_sop_record(record_ids: list[int], override: bool = False, save_new: bool = False) \
            -> list[str] | None:

        """
        如果有重复的SOP记录，返回重复的记录名称列表
        """
        sop_records = await LinsightSOPDao.get_sop_record_by_ids(record_ids)
        records_name_dict = {}
        repeat_names = set()
        name_set = set()
        sop_list = []
        for one in sop_records:
            if one.name not in name_set:
                records_name_dict[one.name] = one
                name_set.add(one.name)
        if name_set:
            sop_list = await LinsightSOPDao.get_sops_by_names(list(name_set))
            for one in sop_list:
                repeat_names.add(one.name)

        if override:
            # 先更新已有的sop库
            for one in sop_list:
                if one_record := records_name_dict.get(one.name):
                    await SOPManageService.update_sop(SOPManagementUpdateSchema(
                        id=one.id,
                        name=one.name,
                        description=one_record.description,
                        content=one_record.content,
                        rating=one_record.rating,
                    ))
                    del records_name_dict[one.name]
            # 再新增剩下的sop记录
            for one in records_name_dict.values():
                await SOPManageService.add_sop(SOPManagementSchema(
                    name=one.name,
                    description=one.description,
                    content=one.content,
                    rating=one.rating,
                ), one.user_id)
        elif save_new:
            for one in sop_records:
                new_name = one.name
                if new_name in repeat_names:
                    # 如果有重复的记录，添加后缀, 长度限制500个字符
                    new_name = f"{one.name}副本"
                await SOPManageService.add_sop(SOPManagementSchema(
                    name=new_name,
                    description=one.description,
                    content=one.content,
                    rating=one.rating,
                ), one.user_id)
            return None
        else:
            # 说明有重复的记录，需要用户确认
            if sop_list:
                return list(repeat_names)
            # 将记录插入到数据库中
            for one in sop_records:
                await SOPManageService.add_sop(SOPManagementSchema(
                    name=one.name,
                    description=one.description,
                    content=one.content,
                    rating=one.rating,
                ), one.user_id)
            return None

    @staticmethod
    async def add_sop(sop_obj: SOPManagementSchema, user_id) -> UnifiedResponseModel | None:
        """
        添加新的SOP
        :param user_id:
        :param sop_obj:
        :return: 添加的SOP对象
        """

        # 获取当前全局配置的embedding模型
        workbench_conf = await LLMService.get_workbench_llm()
        try:
            emb_model_id = workbench_conf.embedding_model.id
            if not emb_model_id:
                return resp_500(code=500, message="未配置知识库embedding模型，请从工作台配置中设置")
        except AttributeError:
            return resp_500(code=500, message="工作台配置中未找到SOP embedding模型，请从工作台配置中设置")

        # 校验embedding模型
        embed_info = LLMDao.get_model_by_id(int(emb_model_id))
        if not embed_info:
            return resp_500(code=500, message="知识库embedding模型不存在，请从工作台配置中设置")
        if embed_info.model_type != LLMModelType.EMBEDDING.value:
            raise ValueError("知识库embedding模型类型错误，请从工作台配置中设置")

        vector_store_id = uuid.uuid4().hex

        embeddings = decide_embeddings(emb_model_id)
        try:
            vector_client: Milvus = decide_vectorstores(
                SOPManageService.collection_name, "Milvus", embeddings
            )

            es_client: ElasticKeywordsSearch = decide_vectorstores(
                SOPManageService.collection_name, "ElasticKeywordsSearch", FakeEmbedding()
            )
            metadatas = [{"vector_store_id": vector_store_id}]
            vector_client.add_texts([sop_obj.content], metadatas=metadatas)
            es_client.add_texts([sop_obj.content], ids=[vector_store_id], metadatas=metadatas)
        except Exception as e:
            return resp_500(code=500, message=f"添加SOP失败，向向量存储添加数据失败: {str(e)}")

        sop_dict = sop_obj.model_dump(exclude_unset=True)
        sop_dict["vector_store_id"] = vector_store_id  # 设置向量存储ID
        # 这里可以添加数据库操作，将sop_obj保存到数据库中
        sop_model = LinsightSOP(**sop_dict)
        sop_model.user_id = user_id
        sop_model = await LinsightSOPDao.create_sop(sop_model)
        if not sop_model:
            return resp_500(code=500, message="添加SOP失败")

        return resp_200(data=sop_model)

    @staticmethod
    async def update_sop(sop_obj: SOPManagementUpdateSchema) -> UnifiedResponseModel | None:
        """
        更新SOP
        :param login_user:
        :param sop_obj:
        :return: 更新后的SOP对象
        """
        # 校验SOP是否存在
        existing_sop = await LinsightSOPDao.get_sops_by_ids([sop_obj.id])
        if not existing_sop:
            return resp_500(code=404, message="SOP不存在")

        if sop_obj.content != existing_sop[0].content:

            # 获取当前全局配置的embedding模型
            workbench_conf = await LLMService.get_workbench_llm()
            try:
                emb_model_id = workbench_conf.embedding_model.id
                if not emb_model_id:
                    return resp_500(code=500, message="未配置知识库embedding模型，请从工作台配置中设置")
            except AttributeError:
                return resp_500(code=500, message="工作台配置中未找到SOP embedding模型，请从工作台配置中设置")

            vector_store_id = existing_sop[0].vector_store_id
            embeddings = decide_embeddings(emb_model_id)

            # 更新向量存储
            try:
                vector_client: Milvus = decide_vectorstores(
                    SOPManageService.collection_name, "Milvus", embeddings
                )
                es_client: ElasticKeywordsSearch = decide_vectorstores(
                    SOPManageService.collection_name, "ElasticKeywordsSearch", FakeEmbedding()
                )

                vector_client.delete(expr=f"vector_store_id == '{vector_store_id}'")
                es_client.delete([vector_store_id])
                metadatas = [{"vector_store_id": vector_store_id}]
                vector_client.add_texts([sop_obj.content], metadatas=metadatas)
                es_client.add_texts([sop_obj.content], ids=[vector_store_id], metadatas=metadatas)

            except Exception as e:
                return resp_500(code=500, message=f"更新SOP失败，向向量存储更新数据失败: {str(e)}")

        # 更新数据库中的SOP
        sop_model = await LinsightSOPDao.update_sop(sop_obj)

        return resp_200(data=sop_model)

    @staticmethod
    async def remove_sop(sop_ids: list[int], login_user: UserPayload) -> UnifiedResponseModel | None:
        """
        删除SOP
        :param login_user:
        :param sop_ids: SOP唯一ID列表
        :return: 删除结果
        """
        if not sop_ids:
            return resp_500(code=400, message="SOP ID列表不能为空")

        # 校验SOP是否存在
        existing_sops = await LinsightSOPDao.get_sops_by_ids(sop_ids)
        if not existing_sops:
            return resp_200(data=True)

        # 删除向量存储中的数据
        try:
            vector_store_ids = [sop.vector_store_id for sop in existing_sops]
            vector_client: Milvus = decide_vectorstores(
                SOPManageService.collection_name, "Milvus", FakeEmbedding()
            )
            es_client: ElasticKeywordsSearch = decide_vectorstores(
                SOPManageService.collection_name, "ElasticKeywordsSearch", FakeEmbedding()
            )

            vector_client.delete(expr=f"vector_store_id in {vector_store_ids}")
            es_client.delete(vector_store_ids)

        except Exception as e:
            return resp_500(code=500, message=f"删除SOP失败，向向量存储删除数据失败: {str(e)}")

        # 删除数据库中的SOP
        await LinsightSOPDao.remove_sop(sop_ids=sop_ids)

        return resp_200(data=True)

    # sop 库检索
    @classmethod
    async def search_sop(cls, query: str, k: int = 3) -> (List[Document], str | None):
        """
        搜索SOP
        :param k:
        :param query: 搜索关键词
        :return: 搜索结果
        """
        # 获取当前全局配置的embedding模型
        try:
            vector_search = True
            es_search = True
            error_msg = None
            workbench_conf = await LLMService.get_workbench_llm()
            if workbench_conf.embedding_model is None or not workbench_conf.embedding_model.id:
                vector_search = False
                error_msg = "请联系管理员检查工作台向量检索模型状态"
            else:
                try:
                    emb_model_id = workbench_conf.embedding_model.id
                    embeddings = decide_embeddings(emb_model_id)
                    await embeddings.aembed_query("test")
                except Exception as e:
                    logger.error(f"向量检索模型初始化失败: {str(e)}")
                    vector_search = False
                    error_msg = "请联系管理员检查工作台向量检索模型状态"

            # 创建文本分割器
            text_splitter = RecursiveCharacterTextSplitter()
            retrievers = []
            if vector_search and es_search:
                emb_model_id = workbench_conf.embedding_model.id
                embeddings = decide_embeddings(emb_model_id)

                vector_client: Milvus = decide_vectorstores(
                    SOPManageService.collection_name, "Milvus", embeddings
                )

                es_client: ElasticKeywordsSearch = decide_vectorstores(
                    SOPManageService.collection_name, "ElasticKeywordsSearch", FakeEmbedding()
                )

                keyword_retriever = KeywordRetriever(keyword_store=es_client, search_kwargs={"k": 100},
                                                     text_splitter=text_splitter)
                baseline_vector_retriever = BaselineVectorRetriever(vector_store=vector_client,
                                                                    search_kwargs={"k": 100},
                                                                    text_splitter=text_splitter)

                retrievers = [keyword_retriever, baseline_vector_retriever]

            elif es_search and not vector_search:
                # 仅使用关键词检索
                es_client: ElasticKeywordsSearch = decide_vectorstores(
                    SOPManageService.collection_name, "ElasticKeywordsSearch", FakeEmbedding()
                )
                keyword_retriever = KeywordRetriever(keyword_store=es_client, search_kwargs={"k": 100},
                                                     text_splitter=text_splitter)
                retrievers = [keyword_retriever]

            elif vector_search and not es_search:
                # 仅使用向量检索
                emb_model_id = workbench_conf.embedding_model.id
                embeddings = decide_embeddings(emb_model_id)

                vector_client: Milvus = decide_vectorstores(
                    SOPManageService.collection_name, "Milvus", embeddings
                )

                baseline_vector_retriever = BaselineVectorRetriever(vector_store=vector_client,
                                                                    search_kwargs={"k": 100},
                                                                    text_splitter=text_splitter)
                retrievers = [baseline_vector_retriever]
            else:
                error_msg = "SOP检索失败，向量检索与关键词检索均不可用"
                return [], error_msg

            retriever = EnsembleRetriever(retrievers=retrievers, weights=[0.5, 0.5] if len(retrievers) > 1 else [1.0])

            # 执行检索
            results = await retriever.ainvoke(input=query)

            if not results:
                return [], error_msg

            vector_store_ids = [doc.metadata.get("vector_store_id") for doc in results if
                                doc.metadata.get("vector_store_id")]

            # 根据vector_store_ids查询库中的sop
            sop_models = await LinsightSOPDao.get_sop_by_vector_store_ids(vector_store_ids)
            sop_model_vector_store_ids = [sop.vector_store_id for sop in sop_models]

            # 过滤结果，确保只返回存在于数据库中的SOP
            results = [doc for doc in results if doc.metadata.get("vector_store_id") in sop_model_vector_store_ids]

            # 过滤完取前k条结果
            results = results[:k]

            return results, error_msg
        except Exception as e:
            logger.error(f"搜索SOP失败: {str(e)}")
            return [], f"SOP检索失败: {str(e)}"

    # 重建SOP VectorStore
    @classmethod
    async def rebuild_sop_vector_store_task(cls, embeddings: Embeddings):
        """
        重建SOP向量存储
        :return: 重建结果
        """
        try:
            # 获取所有SOP
            all_sops = await LinsightSOPDao.get_all_sops()
            if not all_sops:
                logger.info("没有SOP数据需要重建向量存储")
                return None

            # 包装同步函数为异步函数
            def sync_func(sops, emb):
                """
                同步函数，用于重建SOP向量存储
                :param emb:
                :param sops:
                :return:
                """

                vector_client: Milvus = decide_vectorstores(
                    SOPManageService.collection_name, "Milvus", emb
                )
                # 删除现有的向量存储collection
                if vector_client.col is not None:
                    logger.info("删除现有的SOP向量存储collection")
                    vector_client.col.drop()
                    vector_client.col = None
                    vector_client.fields = []

                metadatas = [{"vector_store_id": sop.vector_store_id} for sop in sops]
                contents = [sop.content for sop in sops]

                batch_size = 16
                for i in range(0, len(contents), batch_size):
                    batch_contents = contents[i:i + batch_size]
                    batch_metadatas = metadatas[i:i + batch_size]

                    # 添加新的SOP数据到向量存储
                    vector_client.add_texts(batch_contents, metadatas=batch_metadatas)

                logger.info("SOP向量存储重建完成： {}".format(len(sops)))

            # 使用run_async运行同步函数
            await util.sync_func_to_async(sync_func)(all_sops, embeddings)
            return None


        except Exception as e:
            logger.exception(f"重建SOP向量存储失败: {str(e)}")
            return None

# if __name__ == '__main__':
#     # 测试代码
#     results, error_msg = asyncio.run(SOPManageService.search_sop(query="投标文件编写指南", k=3))
#
#     print(results)
#     print(error_msg)
