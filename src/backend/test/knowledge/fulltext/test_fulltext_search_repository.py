import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_search_repository_impl import (
    KnowledgeFulltextSearchRepositoryImpl,
)
from bisheng.knowledge.domain.schemas.knowledge_fulltext_search_schema import (
    KnowledgeFulltextAdvancedSearchQuery,
    KnowledgeFulltextSearchField,
    KnowledgeFulltextSearchSort,
)


def repository_with_client():
    raw_client = MagicMock()
    client = MagicMock()
    client.open_point_in_time = AsyncMock()
    client.search = AsyncMock()
    client.close_point_in_time = AsyncMock()
    raw_client.options.return_value = client
    return KnowledgeFulltextSearchRepositoryImpl(raw_client), client


def test_query_contract_normalizes_values_and_rejects_invalid_ranges():
    query = KnowledgeFulltextAdvancedSearchQuery(
        space_ids=[3, 1, 3],
        business_domain_code=" pm ",
        file_ext=".PDF",
        all_keywords=" 轧机   振动 ",
        sort="updated_at",
    )

    assert query.space_ids == [1, 3]
    assert query.business_domain_code == "PM"
    assert query.file_ext == "pdf"
    assert query.all_keywords == "轧机 振动"
    assert query.search_field == KnowledgeFulltextSearchField.ALL
    assert query.sort == KnowledgeFulltextSearchSort.UPDATED_AT_DESC

    with pytest.raises(ValidationError, match="preview_count_min"):
        KnowledgeFulltextAdvancedSearchQuery(
            space_ids=[1],
            preview_count_min=10,
            preview_count_max=9,
        )


def test_build_query_combines_text_filters_ranges_and_missing_zero():
    repository, _ = repository_with_client()
    query = KnowledgeFulltextAdvancedSearchQuery(
        space_ids=[9, 7],
        all_keywords="轧机 振动",
        exact_phrase="故障排查",
        any_keywords="轴承 松动",
        exclude_keywords="招标",
        search_field="all",
        tag="设备",
        original_uploader_id=88,
        original_knowledge_id=66,
        preview_count_min=0,
        preview_count_max=10,
        download_count_min=1,
        updated_from=date(2026, 1, 1),
        updated_to=date(2026, 1, 31),
    )

    result = repository.build_query(query)
    serialized = json.dumps(result, ensure_ascii=False)
    filters = result["bool"]["filter"]

    assert filters[0] == {"terms": {"knowledge_id": [7, 9]}}
    assert {"term": {"tags.keyword": "设备"}} in filters
    assert {"term": {"original_uploader_id": 88}} in filters
    assert {"term": {"original_knowledge_id": 66}} in filters
    assert {"range": {"updated_at": {"gte": "2026-01-01", "lt": "2026-02-01"}}} in filters
    assert '"preview_count"' in serialized and '"must_not"' in serialized
    assert {"range": {"download_count": {"gte": 1}}} in filters
    assert serialized.count('"must_not"') >= 2
    for field in ("file_name.substring", "display_title.substring", "tags.substring", "summary.substring", "content.substring"):
        assert field in serialized


def test_content_field_scope_does_not_search_other_fields():
    repository, _ = repository_with_client()
    query = KnowledgeFulltextAdvancedSearchQuery(
        space_ids=[1],
        all_keywords="制度",
        search_field="content",
    )

    serialized = json.dumps(repository.build_query(query), ensure_ascii=False)

    assert "content.substring" in serialized
    assert "file_name.substring" not in serialized
    assert "summary.substring" not in serialized


def test_file_name_field_scope_does_not_search_hidden_display_title():
    repository, _ = repository_with_client()
    query = KnowledgeFulltextAdvancedSearchQuery(
        space_ids=[1],
        all_keywords="天气预报",
        search_field="file_name",
    )

    serialized = json.dumps(repository.build_query(query), ensure_ascii=False)

    assert '"file_name"' in serialized
    assert '"file_name.substring"' in serialized
    assert '"display_title"' not in serialized
    assert '"display_title.substring"' not in serialized


def test_condition_contract_normalizes_first_relation_and_accepts_fuzzy_phrases():
    query = KnowledgeFulltextAdvancedSearchQuery(
        space_ids=[1],
        conditions=[
            {
                "relation": "or",
                "field": "all",
                "match_mode": "fuzzy",
                "value": "设备 故障",
            },
            {
                "relation": "and",
                "field": "knowledge_id",
                "match_mode": "exact",
                "value": 1,
            },
        ],
    )

    assert query.conditions is not None
    assert query.conditions[0].relation is None
    assert query.conditions[0].value == "设备 故障"
    with pytest.raises(ValidationError, match="literal_error"):
        KnowledgeFulltextAdvancedSearchQuery(
            space_ids=[1],
            conditions=[
                {
                    "relation": None,
                    "field": "knowledge_id",
                    "match_mode": "fuzzy",
                    "value": 1,
                }
            ],
        )


def test_condition_query_is_left_associative_and_keeps_scope_outside_expression():
    repository, _ = repository_with_client()
    query = KnowledgeFulltextAdvancedSearchQuery(
        space_ids=[2, 1],
        conditions=[
            {"relation": None, "field": "file_name", "match_mode": "exact", "value": "A"},
            {"relation": "or", "field": "summary", "match_mode": "fuzzy", "value": "B"},
            {"relation": "and", "field": "tags", "match_mode": "exact", "value": "C"},
            {"relation": "not", "field": "preview_count", "match_mode": "exact", "range": {"min": 0, "max": 10}},
        ],
    )

    result = repository.build_query(query)
    expression = result["bool"]["must"][0]
    serialized = json.dumps(expression, ensure_ascii=False)

    assert result["bool"]["filter"] == [{"terms": {"knowledge_id": [1, 2]}}]
    assert expression["bool"]["must_not"]
    assert expression["bool"]["must"][0]["bool"]["must"]
    assert '"minimum_should_match": 1' in serialized
    assert '"match_phrase": {"file_name"' in serialized
    assert '"match": {"summary": {"query": "B", "operator": "and"' in serialized
    assert '"summary.substring"' not in serialized
    assert '"term": {"tags.keyword": "C"}' in serialized
    assert '"display_title"' not in serialized


def test_empty_conditions_compile_to_match_all_with_permission_scope():
    repository, _ = repository_with_client()

    result = repository.build_query(
        KnowledgeFulltextAdvancedSearchQuery(space_ids=[7], conditions=[])
    )

    assert result == {
        "bool": {
            "filter": [{"terms": {"knowledge_id": [7]}}],
            "must": [{"match_all": {}}],
        }
    }


@pytest.mark.parametrize(
    ("sort", "has_keywords", "expected_fields"),
    [
        ("relevance", True, ["_score", "updated_at", "file_id", "_shard_doc"]),
        ("relevance", False, ["updated_at", "file_id", "_shard_doc"]),
        ("updated_at_asc", False, ["updated_at", "file_id", "_shard_doc"]),
        (
            "preview_count_desc",
            True,
            ["preview_count", "_score", "updated_at", "file_id", "_shard_doc"],
        ),
        ("download_count_asc", False, ["download_count", "updated_at", "file_id", "_shard_doc"]),
    ],
)
def test_build_sort_is_stable(sort, has_keywords, expected_fields):
    repository, _ = repository_with_client()
    query = KnowledgeFulltextAdvancedSearchQuery(
        space_ids=[1],
        all_keywords="制度" if has_keywords else None,
        sort=sort,
    )

    result = repository.build_sort(query)

    assert [next(iter(item)) for item in result] == expected_fields
    assert result[-1] == {"_shard_doc": "asc"}


async def test_search_uses_pit_search_after_and_returns_minimal_hits():
    repository, client = repository_with_client()
    client.search.return_value = {
        "pit_id": "pit-2",
        "hits": {
            "hits": [
                {"_id": "11", "_score": 2.5, "sort": [2.5, "2026-01-01", 11, 99]},
            ]
        },
    }
    query = KnowledgeFulltextAdvancedSearchQuery(space_ids=[1], all_keywords="制度")

    result = await repository.search(
        query,
        pit_id="pit-1",
        search_after=[3.0, "2026-02-01", 12, 100],
        size=20,
    )

    assert result.pit_id == "pit-2"
    assert result.hits[0].file_id == 11
    assert result.hits[0].sort_values == [2.5, "2026-01-01", 11, 99]
    assert result.exhausted is True
    kwargs = client.search.await_args.kwargs
    assert kwargs["source"] is False
    assert kwargs["track_total_hits"] is False
    assert kwargs["search_after"] == [3.0, "2026-02-01", 12, 100]
    assert "index" not in kwargs


async def test_uploader_support_query_returns_only_grouped_file_ids():
    repository, client = repository_with_client()
    client.search.return_value = {
        "aggregations": {
            "uploaders": {
                "buckets": [
                    {
                        "key": 8,
                        "support_files": {
                            "hits": {"hits": [{"_id": "101"}, {"_id": "99"}]}
                        },
                    }
                ]
            }
        }
    }

    result = await repository.find_uploader_supports(
        space_ids=[2, 1],
        uploader_ids=[8, 7],
        per_uploader_limit=5,
    )

    assert result[0].user_id == 8
    assert result[0].file_ids == [101, 99]
    kwargs = client.search.await_args.kwargs
    assert kwargs["source"] is False
    assert kwargs["size"] == 0
    assert kwargs["query"]["bool"]["filter"][0] == {"terms": {"knowledge_id": [1, 2]}}
