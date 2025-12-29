import os
import time
import re
from typing import List, Dict, Optional, Union
from elasticsearch import Elasticsearch
from loguru import logger
from bisheng.common.services.config_service import settings

# 默认配置（可通过外部配置文件注入）
DEFAULT_CONFIG = {
    "NGRAM_MIN": 2,
    "NGRAM_MAX": 3
}

# ====================== 2. 生产级ES相似文档检索类（索引绑定版） ======================
class ESSimilarDocNGram:
    """
    生产环境可用的ES中文相似文档检索类（索引与实例绑定）
    核心特性：
    1. 索引名称在构造时确定，所有接口无需再传入索引名
    2. 初始化时自动创建索引（不存在则创建）
    3. 核心接口：insert_doc/delete_doc/search_similar_docs/delete_index
    """

    def __init__(
            self,
            knowledge_id: int
    ):
        """
        初始化ES连接并绑定索引（自动创建索引）
        :param index_name: 绑定的索引名称（必填！）
        :param timeout: ES请求超时时间（秒）
        :param retry_times: ES请求重试次数
        :param ngram_min: ngram最小分词长度，默认2
        :param ngram_max: ngram最大分词长度，默认3
        """
        # 1. 校验索引名称（必填）
        index_name = f"es_similar_doc_ngram_{knowledge_id}".lower()
        if not isinstance(index_name, str) or len(index_name.strip()) == 0:
            raise ValueError("索引名称（index_name）不能为空！")
        self.index_name = index_name.strip()

        # 2. 初始化配置参数
        self.ngram_min =  DEFAULT_CONFIG["NGRAM_MIN"]
        self.ngram_max =  DEFAULT_CONFIG["NGRAM_MAX"]

        # 3. 初始化ES客户端（生产环境建议添加认证、连接池配置）
        try:
            es_conf = settings.get_vectors_conf().elasticsearch
            self.es = Elasticsearch(hosts=es_conf.elasticsearch_url, **es_conf.ssl_verify)
            # 验证ES连接
            if not self.es.ping():
                raise ConnectionError(f"ES连接失败")
            logger.info(f"ES连接成功")
        except Exception as e:
            logger.error(f"ES初始化失败：{str(e)}", exc_info=True)
            raise

        # 4. 初始化时自动创建索引（不存在则创建）
        self._create_index_if_not_exists()

    # ====================== 私有方法：创建索引（初始化时调用） ======================
    def _create_index_if_not_exists(self) -> bool:
        """
        检查索引是否存在，不存在则创建（初始化时自动调用）
        :return: 是否创建了新索引（True=创建，False=已存在）
        """
        # 检查索引是否存在
        if self.es.indices.exists(index=self.index_name):
            logger.info(f"绑定的索引[{self.index_name}]已存在，无需创建")
            return False

        # 构建生产级索引配置（优化ngram参数，适配ES默认限制）
        index_mapping = {
            "settings": {
                "number_of_shards": 1,  # 生产环境建议根据集群规模调整
                "number_of_replicas": 1,  # 生产环境至少1个副本保证高可用
                "index.max_ngram_diff": 2,  # 放开ngram差值限制（适配2-3字）
                "analysis": {
                    "analyzer": {
                        "chinese_ngram_analyzer": {
                            "type": "custom",
                            "tokenizer": "chinese_ngram_tokenizer",
                            "filter": ["lowercase"]
                        }
                    },
                    "tokenizer": {
                        "chinese_ngram_tokenizer": {
                            "type": "ngram",
                            "min_gram": self.ngram_min,
                            "max_gram": self.ngram_max,
                            "token_chars": ["letter", "digit", "symbol", "punctuation"]
                        }
                    }
                }
            },
            "mappings": {
                "properties": {
                    "file_id": {  # 文件唯一ID（核心检索字段）
                        "type": "keyword",
                        "index": True
                    },
                    "file_url": {  # 文件URL
                        "type": "keyword",
                        "index": False  # 不索引，仅存储
                    },
                    "file_content": {  # 文件内容（ngram分词检索）
                        "type": "text",
                        "analyzer": "chinese_ngram_analyzer"
                    },
                    "content_raw": {  # 原始内容（用于预览，不检索）
                        "type": "keyword",
                        "index": False
                    },
                    "create_time": {  # 创建时间
                        "type": "date",
                        "format": "yyyy-MM-dd HH:mm:ss"
                    },
                    "update_time": {  # 更新时间
                        "type": "date",
                        "format": "yyyy-MM-dd HH:mm:ss"
                    }
                }
            }
        }

        try:
            self.es.indices.create(index=self.index_name, body=index_mapping)
            logger.info(f"绑定的索引[{self.index_name}]创建成功")
            return True
        except Exception as e:
            logger.error(f"绑定的索引[{self.index_name}]创建失败：{str(e)}", exc_info=True)
            raise

    # ====================== 私有方法：文本预处理（生产级） ======================
    def preprocess_text(self, text: str) -> str:
        """
        生产级文本预处理：清理噪声，保证分词质量
        :param text: 原始文本
        :return: 预处理后的文本
        """
        if not isinstance(text, str):
            return ""
        # 1. 移除控制字符、不可见字符
        text = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", text)
        # 2. 移除换行、制表符、多余空格
        text = text.replace("\n", "").replace("\r", "").replace("\t", "").strip()
        # 3. 移除特殊符号（保留中文、数字、字母）
        text = re.sub(r"[^\u4e00-\u9fff0-9a-zA-Z]", "", text)
        # 4. 移除过长空白（生产环境防恶意输入）
        text = re.sub(r"\s+", "", text)
        return text

    # ====================== 私有方法：读取本地TXT文件内容 ======================
    def _read_local_txt_file(self, file_path: str) -> str:
        """
        读取本地TXT文件内容（适配多编码）
        :param file_path: 本地文件路径
        :return: 文件内容字符串
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在：{file_path}")
        if not os.path.isfile(file_path):
            raise ValueError(f"不是有效的文件：{file_path}")

        encodings = ["utf-8", "gbk", "gb2312", "utf-8-sig", "latin-1"]
        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    content = f.read()
                logger.info(f"成功读取文件[{file_path}]，编码：{encoding}")
                return content
            except UnicodeDecodeError:
                continue
        raise ValueError(f"文件[{file_path}]编码不支持，尝试的编码：{encodings}")

    # ====================== 公开接口1：插入/更新文档（无需传入索引名） ======================
    def insert_doc(
            self,
            file_id: int,
            file_url: str,
            file_content: str,
            overwrite: bool = True
    ) -> Dict[str, Union[bool, str]]:
        """
        插入文档到绑定的索引（索引已在初始化时创建）
        :param file_id: 文件唯一ID（作为ES文档ID）
        :param file_url: 文件URL
        :param file_content: 文件文本内容
        :param overwrite: 若文档已存在，是否覆盖（True=覆盖，False=跳过）
        :return: 操作结果（success: 是否成功, doc_id: 文档ID, msg: 提示信息）
        """
        # 生产级参数校验
        file_id = str(file_id)
        if not all([file_id, file_url]):
            raise ValueError("file_id、file_url不能为空")
        if not isinstance(file_content, str) or len(file_content.strip()) == 0:
            raise ValueError("file_content不能为空字符串")

        try:
            # 1. 检查文档是否已存在
            doc_exists = False
            try:
                self.es.get(index=self.index_name, id=str(file_id))
                doc_exists = True
            except Exception:
                doc_exists = False

            # 2. 已存在且不覆盖，直接返回
            if doc_exists and not overwrite:
                logger.info(f"文档[{self.index_name}:{file_id}]已存在，跳过插入")
                return {
                    "success": True,
                    "doc_id": file_id,
                    "msg": f"文档已存在，跳过插入"
                }

            # 3. 预处理文本
            processed_content = self.preprocess_text(file_content)
            if len(processed_content) < 10:  # 生产环境防过短文本
                logger.warning(f"文档[{self.index_name}:{file_id}]内容过短（预处理后<10字符）")

            # 4. 构造文档数据
            doc_data = {
                "file_id": file_id,
                "file_url": file_url,
                "file_content": processed_content,
                "content_raw": file_content[:2000],  # 限制原始内容长度，防过大字段
                "create_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "update_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            }

            # 5. 插入/更新文档
            response = self.es.index(
                index=self.index_name,
                id=str(file_id),
                document=doc_data
            )
            # 刷新索引（生产环境可改为异步刷新，提升性能）
            self.es.indices.refresh(index=self.index_name)

            logger.info(f"文档[{self.index_name}:{file_id}]插入成功，ES响应：{response.result}")
            return {
                "success": True,
                "doc_id": file_id,
                "msg": f"文档插入成功（{'覆盖更新' if doc_exists else '新增'}）"
            }
        except Exception as e:
            logger.error(f"文档[{self.index_name}:{file_id}]插入异常：{str(e)}", exc_info=True)
            raise

    # ====================== 公开接口2：删除文档（无需传入索引名） ======================
    def delete_doc(self, file_id: str) -> Dict[str, Union[bool, str]]:
        """
        根据文件ID删除绑定索引中的文档
        :param file_id: 文件唯一ID
        :return: 操作结果（success: 是否成功, doc_id: 文档ID, msg: 提示信息）
        """
        # 参数校验
        if not isinstance(file_id, str) or len(file_id.strip()) == 0:
            raise ValueError("file_id不能为空")

        try:
            # 1. 检查文档是否存在
            try:
                self.es.get(index=self.index_name, id=file_id)
            except Exception as e:
                logger.warning(f"文档[{self.index_name}:{file_id}]不存在，删除操作跳过：{str(e)}")
                return {
                    "success": False,
                    "doc_id": file_id,
                    "msg": "文档不存在，删除失败"
                }

            # 2. 执行删除
            response = self.es.delete(index=self.index_name, id=file_id)
            self.es.indices.refresh(index=self.index_name)

            logger.info(f"文档[{self.index_name}:{file_id}]删除成功，ES响应：{response.result}")
            return {
                "success": True,
                "doc_id": file_id,
                "msg": "文档删除成功"
            }
        except Exception as e:
            logger.error(f"文档[{self.index_name}:{file_id}]删除异常：{str(e)}", exc_info=True)
            raise

    # ====================== 公开接口3：相似文档检索（无需传入索引名） ======================
    def search_similar_docs_plus(self,query_text: str, top_n: int = 10) -> List[str]:
        """
        批量检索相似文档
        :param query_texts: 包含多个查询文本的列表
        :param top_n: 返回每个查询的前n个相似文件ID
        :return: 包含多个相似文件ID列表的二维列表
        """
        # 参数校验
        if not query_text or not all(isinstance(q, str) for q in query_text):
            raise ValueError("query_texts必须是非空字符串列表")
        if not isinstance(top_n, int) or top_n < 1 or top_n > 100:  # 生产环境限制最大返回数
            raise ValueError("top_n必须是1-100之间的整数")

        result = set()
        max_len = 2000
        for i in range(len(query_text)//max_len + 1):
            query = query_text[i*max_len:(i+1)*max_len]
            result.update(self._search_similar_docs_short(query, top_n))
        return list(result)

    def search_similar_docs(
            self,
            query_text: str,
            top_n: int = 10
    ) -> List[str]:
        # 参数校验
        if not isinstance(query_text, str) or len(query_text.strip()) == 0:
            raise ValueError("query_text不能为空")
        if not isinstance(top_n, int) or top_n < 1 or top_n > 100:  # 生产环境限制最大返回数
            raise ValueError("top_n必须是1-100之间的整数")
        processed_query = self.preprocess_text(query_text)
        if len(processed_query) < 3000:
            return self._search_similar_docs_short(query_text, top_n)
        else:
            return self._search_similar_docs_long(query_text, top_n)

    def _search_similar_docs_long(
            self,
            query_text: str,
            top_n: int = 10
    ) -> List[str]:
        """
        根据文本检索绑定索引中前n个最相似的文件ID
        :param query_text: 检索的文本字符串（txt内容）
        :param top_n: 返回前n个相似文件ID
        :return: 相似文件ID列表（按相似度降序排列）
        """
        # 参数校验
        if not isinstance(query_text, str) or len(query_text.strip()) == 0:
            raise ValueError("query_text不能为空")
        if not isinstance(top_n, int) or top_n < 1 or top_n > 100:  # 生产环境限制最大返回数
            raise ValueError("top_n必须是1-100之间的整数")

        try:
            # 1. 预处理查询文本
            processed_query = self.preprocess_text(query_text)
            if len(processed_query) < 10:
                logger.warning(f"查询文本过短（预处理后<10字符），可能影响检索效果")
                return []

            # 2. 执行MLT相似检索
            response = self.es.search(
                index=self.index_name,
                body={
                    "size": top_n,
                    "query": {
                        "more_like_this": {
                            "fields": ["file_content"],
                            "like": processed_query,
                            "min_term_freq": 2,
                            "max_doc_freq": 50,  # 生产环境放宽，适配更多文档
                            "min_word_length": 2,
                            "max_word_length": 10,
                            "boost_terms": 3.0,
                            "include": False
                        }
                    },
                    "_source": ["file_id"]  # 仅返回file_id，减少数据传输
                }
            )

            # 3. 解析结果，提取file_id（按相似度降序）
            similar_file_ids = []
            for hit in response["hits"]["hits"]:
                similar_file_ids.append(hit["_source"]["file_id"])

            logger.info(f"索引[{self.index_name}]检索完成，返回{len(similar_file_ids)}个相似文件ID")
            return similar_file_ids[:top_n]  # 确保返回数量不超过top_n
        except Exception as e:
            logger.error(f"索引[{self.index_name}]检索异常：{str(e)}", exc_info=True)
            raise

    def _search_similar_docs_short(
            self,
            query_text: str,
            top_n: int = 1000
    ) -> List[str]:
        if not query_text:
            raise ValueError("query_text不能为空")
        if not isinstance(top_n, int) or top_n < 1:
            raise ValueError("top_n必须是大于0的整数")

        # 预处理查询文本（截断过长文本，避免分词超限）
        processed_query = self.preprocess_text(query_text)

        try:
            # 改用simple_query_string：生成更少的布尔子句，避免maxClauseCount超限
            match_response = self.es.search(
                index=self.index_name,
                body={
                    "size": top_n,
                    "query": {
                        "simple_query_string": {
                            "query": processed_query,
                            "fields": ["file_content"],
                            "default_operator": "OR",  # 任意词匹配，确保所有文档召回
                            "flags": "ALL",
                            "boost": 1.0
                        }
                    },
                    "_source": ["file_id"],
                    "sort": [{"_score": {"order": "desc"}}],
                    "track_total_hits": True
                }
            )

            # 提取所有匹配的file_id
            match_ids = [hit["_source"]["file_id"] for hit in match_response["hits"]["hits"]]
            # 打印分数
            # for hit in match_response["hits"]["hits"]:
            #     logger.info(f"文档[{hit['_source']['file_id']}] 匹配分数：{hit['_score']}")

            logger.info(f"共检索到{len(match_ids)}个文档：{match_ids}")
            return match_ids[:top_n]

        except Exception as e:
            logger.error(f"检索失败：{str(e)}")
            raise

    def get_doc_full_content(self, file_id: str) -> str:
        """
        根据file_id获取绑定索引中该文件的file_content字段内容（预处理后的检索用内容）
        :param file_id: 文件唯一ID
        :return: 结果字典（success: 是否成功, content: file_content字段内容, msg: 提示信息）
        """
        # 参数校验
        if not file_id:
            raise ValueError("file_id不能为空")

        try:
            # 从ES获取文档，指定读取file_content字段
            response = self.es.get(
                index=self.index_name,
                id=file_id,
                _source=["file_content"]  # 读取预处理后的检索用内容字段
            )

            # 提取file_content字段内容
            full_content = response["_source"].get("file_content", "")
            logger.info(f"成功获取文档[{self.index_name}:{file_id}]的file_content内容")
            return full_content
        except Exception as e:
            return ""

    # ====================== 公开接口4：删除绑定的索引（无需传入索引名） ======================
    def delete_index(self) -> Dict[str, Union[bool, str]]:
        """
        删除当前绑定的ES索引（生产环境慎用！）
        :return: 操作结果（success: 是否成功, msg: 提示信息）
        """
        try:
            # 1. 检查索引是否存在
            if not self.es.indices.exists(index=self.index_name):
                logger.warning(f"绑定的索引[{self.index_name}]不存在，删除操作跳过")
                return {
                    "success": False,
                    "msg": f"索引[{self.index_name}]不存在，删除失败"
                }

            # 2. 执行删除（生产环境建议添加二次确认）
            response = self.es.indices.delete(index=self.index_name)
            logger.warning(f"绑定的索引[{self.index_name}]已删除，ES响应：{response.result}")  # 警告级别，提醒慎用
            return {
                "success": True,
                "msg": f"索引[{self.index_name}]删除成功"
            }

        except Exception as e:
            logger.error(f"索引[{self.index_name}]删除异常：{str(e)}", exc_info=True)
            raise

    # ====================== 生产环境：资源释放 ======================
    def close(self):
        """关闭ES连接（生产环境优雅退出）"""
        try:
            self.es.close()
            logger.info("ES连接已关闭")
        except Exception as e:
            logger.error(f"关闭ES连接失败：{str(e)}", exc_info=True)

    def __del__(self):
        """析构函数，自动释放连接"""
        try:
            self.close()
        except:
            pass