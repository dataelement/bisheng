"""基于全局全文索引的门户高级检索实现。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from elasticsearch import AsyncElasticsearch

from bisheng.knowledge.domain import knowledge_fulltext_constants as constants
from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_search_repository import (
    KnowledgeFulltextSearchRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_fulltext_search_schema import (
    KnowledgeFulltextAdvancedSearchQuery,
    KnowledgeFulltextCondition,
    KnowledgeFulltextConditionMatchMode,
    KnowledgeFulltextConditionRelation,
    KnowledgeFulltextCountCondition,
    KnowledgeFulltextDateCondition,
    KnowledgeFulltextDocumentCategoryCondition,
    KnowledgeFulltextSearchBatch,
    KnowledgeFulltextSearchField,
    KnowledgeFulltextSearchHit,
    KnowledgeFulltextSearchSort,
    KnowledgeFulltextSelectCondition,
    KnowledgeFulltextTextCondition,
    KnowledgeFulltextUploaderSupport,
)

_SEARCH_FIELD_MAP: dict[KnowledgeFulltextSearchField, tuple[str, ...]] = {
    KnowledgeFulltextSearchField.ALL: (
        "file_name",
        "display_title",
        "tags",
        "summary",
        "content",
    ),
    KnowledgeFulltextSearchField.FILE_NAME: ("file_name",),
    KnowledgeFulltextSearchField.SUMMARY: ("summary",),
    KnowledgeFulltextSearchField.TAGS: ("tags",),
    KnowledgeFulltextSearchField.CONTENT: ("content",),
}


class KnowledgeFulltextSearchRepositoryImpl(KnowledgeFulltextSearchRepository):
    def __init__(self, client: AsyncElasticsearch):
        self.client = client.options(
            request_timeout=constants.KNOWLEDGE_FULLTEXT_SEARCH_REQUEST_TIMEOUT_SECONDS
        )

    @staticmethod
    def _split_terms(value: str | None) -> list[str]:
        return value.split() if value else []

    @staticmethod
    def _field_boost(field: str, search_field: KnowledgeFulltextSearchField) -> float:
        if search_field == KnowledgeFulltextSearchField.ALL:
            return constants.KNOWLEDGE_FULLTEXT_SEARCH_FIELD_BOOSTS[field]
        return 1.0

    def _term_clause(
        self,
        term: str,
        *,
        search_field: KnowledgeFulltextSearchField,
    ) -> dict[str, Any]:
        queries: list[dict[str, Any]] = []
        for field in _SEARCH_FIELD_MAP[search_field]:
            boost = self._field_boost(field, search_field)
            queries.extend(
                [
                    {
                        "match": {
                            field: {
                                "query": term,
                                "operator": "and",
                                "boost": boost,
                            }
                        }
                    },
                    {
                        "match": {
                            f"{field}.substring": {
                                "query": term,
                                "operator": "and",
                                "boost": boost,
                            }
                        }
                    },
                ]
            )
        return {"dis_max": {"queries": queries, "tie_breaker": 0.1}}

    def _phrase_clause(
        self,
        phrase: str,
        *,
        search_field: KnowledgeFulltextSearchField,
    ) -> dict[str, Any]:
        queries: list[dict[str, Any]] = []
        for field in _SEARCH_FIELD_MAP[search_field]:
            boost = self._field_boost(field, search_field)
            queries.append(
                {
                    "match_phrase": {
                        field: {
                            "query": phrase,
                            "boost": boost,
                        }
                    }
                }
            )
            if len(phrase) <= constants.KNOWLEDGE_FULLTEXT_NGRAM_MAX:
                queries.append(
                    {
                        "match": {
                            f"{field}.substring": {
                                "query": phrase,
                                "operator": "and",
                                "boost": boost,
                            }
                        }
                    }
                )
        return {"dis_max": {"queries": queries, "tie_breaker": 0.1}}

    def _condition_text_clause(
        self,
        condition: KnowledgeFulltextTextCondition,
    ) -> dict[str, Any]:
        search_field = KnowledgeFulltextSearchField(condition.field)
        if (
            condition.field == KnowledgeFulltextSearchField.TAGS.value
            and condition.match_mode == KnowledgeFulltextConditionMatchMode.EXACT
        ):
            return {"term": {"tags.keyword": condition.value}}

        queries: list[dict[str, Any]] = []
        for field in _SEARCH_FIELD_MAP[search_field]:
            boost = self._field_boost(field, search_field)
            if condition.match_mode == KnowledgeFulltextConditionMatchMode.EXACT:
                queries.append(
                    {"match_phrase": {field: {"query": condition.value, "boost": boost}}}
                )
            else:
                queries.append(
                    {
                        "match": {
                            field: {
                                "query": condition.value,
                                "operator": "and",
                                "boost": boost,
                            }
                        }
                    }
                )
        if len(queries) == 1:
            return queries[0]
        return {"dis_max": {"queries": queries, "tie_breaker": 0.1}}

    def _condition_clause(self, condition: KnowledgeFulltextCondition) -> dict[str, Any]:
        if isinstance(condition, KnowledgeFulltextTextCondition):
            return self._condition_text_clause(condition)
        if isinstance(condition, KnowledgeFulltextSelectCondition):
            field_map = {
                "knowledge_level": "knowledge_level",
                "knowledge_id": "knowledge_id",
                "business_domain_code": "business_domain_code",
                "file_ext": "file_ext",
                "original_uploader_id": "original_uploader_id",
                "original_knowledge_id": "original_knowledge_id",
            }
            return {"term": {field_map[condition.field]: condition.value}}
        if isinstance(condition, KnowledgeFulltextDocumentCategoryCondition):
            clauses: list[dict[str, Any]] = []
            if condition.value.document_type is not None:
                clauses.append(
                    {"term": {"document_category_code": condition.value.document_type}}
                )
            if condition.value.file_subcategory_code is not None:
                clauses.append(
                    {"term": {"file_subcategory_code": condition.value.file_subcategory_code}}
                )
            return clauses[0] if len(clauses) == 1 else {"bool": {"must": clauses}}
        if isinstance(condition, KnowledgeFulltextCountCondition):
            clause = self._count_range_clause(
                condition.field,
                condition.range.min,
                condition.range.max,
            )
            if clause is None:  # pragma: no cover - schema guarantees one bound
                return {"match_all": {}}
            return clause
        if isinstance(condition, KnowledgeFulltextDateCondition):
            bounds: dict[str, str] = {}
            if condition.range.from_date is not None:
                bounds["gte"] = condition.range.from_date.isoformat()
            if condition.range.to is not None:
                bounds["lt"] = (condition.range.to + timedelta(days=1)).isoformat()
            return {"range": {"updated_at": bounds}}
        raise TypeError(f"Unsupported fulltext condition: {type(condition).__name__}")

    def _compile_conditions(
        self,
        conditions: list[KnowledgeFulltextCondition],
    ) -> dict[str, Any]:
        if not conditions:
            return {"match_all": {}}
        expression = self._condition_clause(conditions[0])
        for condition in conditions[1:]:
            current = self._condition_clause(condition)
            if condition.relation == KnowledgeFulltextConditionRelation.OR:
                expression = {
                    "bool": {
                        "should": [expression, current],
                        "minimum_should_match": 1,
                    }
                }
            elif condition.relation == KnowledgeFulltextConditionRelation.NOT:
                expression = {"bool": {"must": [expression], "must_not": [current]}}
            else:
                expression = {"bool": {"must": [expression, current]}}
        return expression

    @staticmethod
    def _count_range_clause(
        field: str,
        lower: int | None,
        upper: int | None,
    ) -> dict[str, Any] | None:
        if lower is None and upper is None:
            return None
        bounds: dict[str, int] = {}
        if lower is not None:
            bounds["gte"] = lower
        if upper is not None:
            bounds["lte"] = upper
        range_clause = {"range": {field: bounds}}
        if lower is not None and lower > 0:
            return range_clause
        return {
            "bool": {
                "should": [
                    range_clause,
                    {"bool": {"must_not": [{"exists": {"field": field}}]}},
                ],
                "minimum_should_match": 1,
            }
        }

    def build_query(self, query: KnowledgeFulltextAdvancedSearchQuery) -> dict[str, Any]:
        if query.conditions is not None:
            return {
                "bool": {
                    "filter": [{"terms": {"knowledge_id": query.space_ids}}],
                    "must": [self._compile_conditions(query.conditions)],
                }
            }

        must: list[dict[str, Any]] = []
        must_not: list[dict[str, Any]] = []
        filters: list[dict[str, Any]] = [{"terms": {"knowledge_id": query.space_ids}}]

        for term in self._split_terms(query.all_keywords):
            must.append(self._term_clause(term, search_field=query.search_field))
        if query.exact_phrase:
            must.append(self._phrase_clause(query.exact_phrase, search_field=query.search_field))
        any_terms = self._split_terms(query.any_keywords)
        if any_terms:
            must.append(
                {
                    "bool": {
                        "should": [
                            self._term_clause(term, search_field=query.search_field)
                            for term in any_terms
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )
        for term in self._split_terms(query.exclude_keywords):
            must_not.append(self._term_clause(term, search_field=query.search_field))

        exact_filters = (
            ("knowledge_level", query.space_level),
            ("business_domain_code", query.business_domain_code),
            ("document_category_code", query.document_type),
            ("file_subcategory_code", query.file_subcategory_code),
            ("file_ext", query.file_ext),
            ("tags.keyword", query.tag),
            ("original_uploader_id", query.original_uploader_id),
            ("original_knowledge_id", query.original_knowledge_id),
        )
        filters.extend({"term": {field: value}} for field, value in exact_filters if value is not None)

        updated_bounds: dict[str, str] = {}
        if query.updated_from is not None:
            updated_bounds["gte"] = query.updated_from.isoformat()
        if query.updated_to is not None:
            updated_bounds["lt"] = (query.updated_to + timedelta(days=1)).isoformat()
        if updated_bounds:
            filters.append({"range": {"updated_at": updated_bounds}})

        for count_clause in (
            self._count_range_clause(
                "preview_count", query.preview_count_min, query.preview_count_max
            ),
            self._count_range_clause(
                "download_count", query.download_count_min, query.download_count_max
            ),
        ):
            if count_clause is not None:
                filters.append(count_clause)

        bool_query: dict[str, Any] = {"filter": filters}
        bool_query["must"] = must or [{"match_all": {}}]
        if must_not:
            bool_query["must_not"] = must_not
        return {"bool": bool_query}

    @staticmethod
    def build_sort(query: KnowledgeFulltextAdvancedSearchQuery) -> list[dict[str, Any]]:
        if query.sort == KnowledgeFulltextSearchSort.RELEVANCE:
            if query.has_keywords:
                return [
                    {"_score": {"order": "desc"}},
                    {"updated_at": {"order": "desc", "missing": "_last"}},
                    {"file_id": {"order": "desc"}},
                    {"_shard_doc": "asc"},
                ]
            return [
                {"updated_at": {"order": "desc", "missing": "_last"}},
                {"file_id": {"order": "desc"}},
                {"_shard_doc": "asc"},
            ]

        if query.sort in {
            KnowledgeFulltextSearchSort.UPDATED_AT_DESC,
            KnowledgeFulltextSearchSort.UPDATED_AT_ASC,
        }:
            direction = "desc" if query.sort.value.endswith("_desc") else "asc"
            return [
                {"updated_at": {"order": direction, "missing": "_last"}},
                {"file_id": {"order": direction}},
                {"_shard_doc": "asc"},
            ]

        field = (
            "preview_count"
            if query.sort
            in {
                KnowledgeFulltextSearchSort.PREVIEW_COUNT_DESC,
                KnowledgeFulltextSearchSort.PREVIEW_COUNT_ASC,
            }
            else "download_count"
        )
        direction = "desc" if query.sort.value.endswith("_desc") else "asc"
        result: list[dict[str, Any]] = [{field: {"order": direction, "missing": 0}}]
        if query.has_keywords:
            result.append({"_score": {"order": "desc"}})
        result.extend(
            [
                {"updated_at": {"order": "desc", "missing": "_last"}},
                {"file_id": {"order": "desc"}},
                {"_shard_doc": "asc"},
            ]
        )
        return result

    async def open_pit(self) -> str:
        response = await self.client.open_point_in_time(
            index=constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS,
            keep_alive=constants.KNOWLEDGE_FULLTEXT_SEARCH_PIT_KEEP_ALIVE,
        )
        return str(response["id"])

    async def search(
        self,
        query: KnowledgeFulltextAdvancedSearchQuery,
        *,
        pit_id: str,
        search_after: list[Any] | None,
        size: int,
    ) -> KnowledgeFulltextSearchBatch:
        kwargs: dict[str, Any] = {
            "query": self.build_query(query),
            "sort": self.build_sort(query),
            "size": size,
            "pit": {
                "id": pit_id,
                "keep_alive": constants.KNOWLEDGE_FULLTEXT_SEARCH_PIT_KEEP_ALIVE,
            },
            "source": False,
            "track_total_hits": False,
        }
        if search_after is not None:
            kwargs["search_after"] = search_after
        response = await self.client.search(**kwargs)
        raw_hits = list((response.get("hits") or {}).get("hits") or [])
        hits = [
            KnowledgeFulltextSearchHit(
                file_id=int(item["_id"]),
                score=item.get("_score"),
                sort_values=list(item.get("sort") or []),
            )
            for item in raw_hits
        ]
        return KnowledgeFulltextSearchBatch(
            pit_id=str(response.get("pit_id") or pit_id),
            hits=hits,
            exhausted=len(raw_hits) < size,
        )

    async def close_pit(self, pit_id: str) -> None:
        await self.client.close_point_in_time(id=pit_id)

    async def find_uploader_supports(
        self,
        *,
        space_ids: list[int],
        uploader_ids: list[int],
        per_uploader_limit: int,
    ) -> list[KnowledgeFulltextUploaderSupport]:
        if not space_ids or not uploader_ids:
            return []
        response = await self.client.search(
            index=constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS,
            size=0,
            source=False,
            track_total_hits=False,
            query={
                "bool": {
                    "filter": [
                        {"terms": {"knowledge_id": sorted(set(space_ids))}},
                        {"terms": {"original_uploader_id": sorted(set(uploader_ids))}},
                    ]
                }
            },
            aggs={
                "uploaders": {
                    "terms": {
                        "field": "original_uploader_id",
                        "size": len(set(uploader_ids)),
                    },
                    "aggs": {
                        "support_files": {
                            "top_hits": {
                                "size": per_uploader_limit,
                                "_source": False,
                                "sort": [{"file_id": {"order": "desc"}}],
                            }
                        }
                    },
                }
            },
        )
        buckets = ((response.get("aggregations") or {}).get("uploaders") or {}).get("buckets") or []
        return [
            KnowledgeFulltextUploaderSupport(
                user_id=int(bucket["key"]),
                file_ids=[
                    int(hit["_id"])
                    for hit in (((bucket.get("support_files") or {}).get("hits") or {}).get("hits") or [])
                ],
            )
            for bucket in buckets
        ]
