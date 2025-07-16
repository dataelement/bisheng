import asyncio
import uuid
from typing import List
from loguru import logger
from langchain_core.documents import Document

from bisheng_langchain.rag.init_retrievers import KeywordRetriever, BaselineVectorRetriever
from langchain_text_splitters import RecursiveCharacterTextSplitter

from bisheng.api.services.llm import LLMService
from bisheng_langchain.retrievers import EnsembleRetriever
from bisheng_langchain.vectorstores import ElasticKeywordsSearch, Milvus

from bisheng.api.services.knowledge_imp import decide_vectorstores
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schema.inspiration_schema import SOPManagementSchema, SOPManagementUpdateSchema
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_500, resp_200
from bisheng.database.models.linsight_sop import LinsightSOP, LinsightSOPDao
from bisheng.database.models.llm_server import LLMDao, LLMModelType
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.utils.embedding import decide_embeddings


class SOPManageService:
    __doc__ = "灵思SOP管理服务"

    collection_name = "col_linsight_sop"

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

            vector_client.add_texts([sop_obj.content], metadatas=[{"vector_store_id": vector_store_id}])
            es_client.add_texts([sop_obj.content], ids=[vector_store_id])
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
                vector_client.add_texts([sop_obj.content], metadatas=[{"vector_store_id": vector_store_id}])
                es_client.add_texts([sop_obj.content], ids=[vector_store_id])

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

