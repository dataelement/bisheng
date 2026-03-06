"""
文章 ES CRUD Service

封装对 ES 文章索引的所有操作：索引、批量索引、获取、更新、删除、搜索。
所有方法均为 async，使用 get_es_connection 获取 AsyncElasticsearch 客户端。
"""
import logging
from typing import List, Optional, Dict, Any

from elasticsearch import AsyncElasticsearch, helpers as es_helpers

from bisheng.channel.domain.es.article_index import (
    ARTICLE_INDEX_NAME,
    ensure_article_index_exists,
)
from bisheng.channel.domain.schemas.article_schema import (
    ArticleDocument,
    ArticleSearchResultItem,
    ArticleSearchPageResponse,
)
from bisheng.core.search.elasticsearch.manager import get_es_connection

logger = logging.getLogger(__name__)


class ArticleEsService:
    """文章 ES Service，封装对 channel_articles 索引的所有操作"""

    def __init__(self):
        self._es_client: Optional[AsyncElasticsearch] = None

    async def _get_client(self) -> AsyncElasticsearch:
        """获取 ES 客户端，懒加载"""
        if self._es_client is None:
            self._es_client = await get_es_connection()
        return self._es_client

    async def ensure_index(self) -> None:
        """确保文章索引存在"""
        client = await self._get_client()
        await ensure_article_index_exists(client)

    # ──────────────────────────────────────────
    #  Create
    # ──────────────────────────────────────────

    async def index_article(self, article: ArticleDocument, doc_id: Optional[str] = None) -> str:
        """
        索引单篇文章。

        Args:
            article: 文章文档
            doc_id: 可选的文档 ID，不传则由 ES 自动生成

        Returns:
            文档 ID
        """
        client = await self._get_client()
        body = article.model_dump(mode='json')

        kwargs: Dict[str, Any] = {
            "index": ARTICLE_INDEX_NAME,
            "body": body,
        }
        if doc_id:
            kwargs["id"] = doc_id

        result = await client.index(**kwargs)
        return result["_id"]

    async def bulk_index_articles(self, articles: List[ArticleDocument],
                                  doc_ids: Optional[List[str]] = None) -> int:
        """
        批量索引文章。

        Args:
            articles: 文章列表
            doc_ids: 可选的文档 ID 列表，长度需与 articles 一致

        Returns:
            成功索引的文档数
        """
        if not articles:
            return 0

        client = await self._get_client()
        actions = []
        for i, article in enumerate(articles):
            action = {
                "_index": ARTICLE_INDEX_NAME,
                "_source": article.model_dump(mode='json'),
            }
            if doc_ids and i < len(doc_ids) and doc_ids[i]:
                action["_id"] = doc_ids[i]
            actions.append(action)

        success, errors = await es_helpers.async_bulk(client, actions, raise_on_error=False)
        if errors:
            logger.warning(f"Bulk index completed with {len(errors)} errors: {errors[:3]}")
        return success

    # ──────────────────────────────────────────
    #  Read
    # ──────────────────────────────────────────

    async def get_article(self, doc_id: str) -> Optional[ArticleSearchResultItem]:
        """
        根据文档 ID 获取文章。

        Args:
            doc_id: ES 文档 ID

        Returns:
            文章搜索结果项，若不存在则返回 None
        """
        client = await self._get_client()
        try:
            result = await client.get(index=ARTICLE_INDEX_NAME, id=doc_id)
            source = result["_source"]
            return ArticleSearchResultItem(doc_id=result["_id"], **source)
        except Exception:
            logger.debug(f"Article not found: {doc_id}")
            return None

    # ──────────────────────────────────────────
    #  Update
    # ──────────────────────────────────────────

    async def update_article(self, doc_id: str, updates: Dict[str, Any]) -> bool:
        """
        部分更新文章字段。

        Args:
            doc_id: ES 文档 ID
            updates: 需要更新的字段字典

        Returns:
            是否成功
        """
        client = await self._get_client()
        try:
            await client.update(
                index=ARTICLE_INDEX_NAME,
                id=doc_id,
                body={"doc": updates},
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update article {doc_id}: {e}")
            return False

    # ──────────────────────────────────────────
    #  Delete
    # ──────────────────────────────────────────

    async def delete_article(self, doc_id: str) -> bool:
        """
        删除文章。

        Args:
            doc_id: ES 文档 ID

        Returns:
            是否成功
        """
        client = await self._get_client()
        try:
            await client.delete(index=ARTICLE_INDEX_NAME, id=doc_id)
            return True
        except Exception as e:
            logger.error(f"Failed to delete article {doc_id}: {e}")
            return False

    # ──────────────────────────────────────────
    #  Search
    # ──────────────────────────────────────────

    async def search_articles(
            self,
            source_ids: Optional[List[str]] = None,
            keyword: Optional[str] = None,
            filter_rules: Optional[List[Dict[str, Any]]] = None,
            page: int = 1,
            page_size: int = 20,
    ) -> ArticleSearchPageResponse:
        """
        检索文章，支持信源过滤、关键词搜索、过滤规则、高亮和分页。

        Args:
            source_ids: 信源 ID 列表过滤
            keyword: 搜索关键词（匹配标题、正文、信源ID）
            filter_rules: 频道过滤规则列表
                          每条规则格式: {"rule_type": "include"/"exclude",
                                        "keywords": [...], "relation": "and"/"or"}
            page: 页码（从 1 开始）
            page_size: 每页数量

        Returns:
            ArticleSearchPageResponse
        """
        client = await self._get_client()

        # 构建 bool 查询
        must_clauses = []
        must_not_clauses = []
        filter_clauses = []

        # 1. 信源 ID 过滤
        if source_ids:
            filter_clauses.append({
                "terms": {"source_id": source_ids}
            })

        # 2. 关键词搜索（标题 + 正文 + 信源ID）
        if keyword:
            must_clauses.append({
                "multi_match": {
                    "query": keyword,
                    "fields": ["title^3", "content", "source_id"],
                    "type": "best_fields",
                }
            })

        # 3. 频道过滤规则
        if filter_rules:
            for rule in filter_rules:
                rule_type = rule.get("rule_type")
                keywords = rule.get("keywords", [])
                relation = rule.get("relation", "or")

                if not keywords:
                    continue

                # 构建关键词匹配子查询
                keyword_queries = []
                for kw in keywords:
                    keyword_queries.append({
                        "multi_match": {
                            "query": kw,
                            "fields": ["title", "content"],
                            "type": "best_fields",
                        }
                    })

                if relation == "and":
                    combined = {"bool": {"must": keyword_queries}}
                else:
                    combined = {"bool": {"should": keyword_queries, "minimum_should_match": 1}}

                if rule_type == "include":
                    must_clauses.append(combined)
                elif rule_type == "exclude":
                    must_not_clauses.append(combined)

        # 组装完整查询
        bool_query: Dict[str, Any] = {}
        if must_clauses:
            bool_query["must"] = must_clauses
        if must_not_clauses:
            bool_query["must_not"] = must_not_clauses
        if filter_clauses:
            bool_query["filter"] = filter_clauses

        if bool_query:
            query = {"bool": bool_query}
        else:
            query = {"match_all": {}}

        # 高亮配置
        highlight_config = {}
        if keyword:
            highlight_config = {
                "pre_tags": ["<em>"],
                "post_tags": ["</em>"],
                "fields": {
                    "title": {"number_of_fragments": 0},
                    "content": {"fragment_size": 200, "number_of_fragments": 3},
                },
            }

        # 构建请求体
        from_offset = (page - 1) * page_size
        body: Dict[str, Any] = {
            "query": query,
            "sort": [{"update_time": {"order": "desc"}}],
            "from": from_offset,
            "size": page_size,
            "_source": True,
        }
        if highlight_config:
            body["highlight"] = highlight_config

        # 执行搜索
        response = await client.search(index=ARTICLE_INDEX_NAME, body=body)

        # 解析结果
        total = response["hits"]["total"]
        if isinstance(total, dict):
            total_count = total["value"]
        else:
            total_count = total

        items = []
        for hit in response["hits"]["hits"]:
            source = hit["_source"]
            highlight = hit.get("highlight")

            item = ArticleSearchResultItem(
                doc_id=hit["_id"],
                score=hit.get("_score"),
                highlight=highlight,
                **source,
            )
            items.append(item)

        return ArticleSearchPageResponse(
            data=items,
            total=total_count,
            page=page,
            page_size=page_size,
        )
