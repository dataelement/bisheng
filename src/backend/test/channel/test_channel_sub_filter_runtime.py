from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from bisheng.channel.domain.services import article_es_service as article_es_service_module
from bisheng.channel.domain.services.article_es_service import ArticleEsService


def _single_rule(rule_type: str = "exclude", keywords: list[str] | None = None) -> dict:
    return {
        "type": "single",
        "rule_type": rule_type,
        "keywords": keywords or ["北大"],
    }


def _rule_group(
    channel_type: str,
    rule_type: str = "exclude",
    keywords: list[str] | None = None,
    relation: str = "or",
    rules: list[dict] | None = None,
) -> dict:
    return {
        "relation": relation,
        "rules": rules or [_single_rule(rule_type, keywords)],
        "channel_type": channel_type,
    }


def _runtime_mapping(query_parts):
    assert query_parts.runtime_mappings
    return next(iter(query_parts.runtime_mappings.items()))


def _runtime_terms(query_parts):
    return [{"term": {field_name: True}} for field_name in query_parts.runtime_mappings]


def _collect_bool_queries(value):
    if isinstance(value, dict):
        bool_query = value.get("bool")
        if isinstance(bool_query, dict):
            yield bool_query
        for child in value.values():
            yield from _collect_bool_queries(child)
    elif isinstance(value, list):
        for child in value:
            yield from _collect_bool_queries(child)


def test_sub_channel_rules_use_runtime_source_filter():
    svc = ArticleEsService()

    query_parts = svc._build_count_query_parts(source_ids=["s1"], filter_rules=[_rule_group("sub")])

    runtime_field_name, runtime_field = _runtime_mapping(query_parts)
    query_json = json.dumps(query_parts.query, ensure_ascii=False)

    assert runtime_field["type"] == "boolean"
    assert runtime_field["script"]["params"] == {"keywords": ["北大"]}
    assert f'"{runtime_field_name}": true' in query_json
    assert "match_phrase" not in query_json


def test_main_channel_rules_keep_match_phrase_without_runtime_mapping():
    svc = ArticleEsService()

    query_parts = svc._build_count_query_parts(source_ids=["s1"], filter_rules=[_rule_group("main")])
    query_json = json.dumps(query_parts.query, ensure_ascii=False)

    assert query_parts.runtime_mappings == {}
    assert '"match_phrase"' in query_json
    assert '"title": {"query": "北大"}' in query_json
    assert '"content": {"query": "北大"}' in query_json


def test_sub_channel_and_excludes_use_independent_must_not_clauses():
    svc = ArticleEsService()

    query_parts = svc._build_count_query_parts(
        source_ids=["s1"],
        filter_rules=[
            _rule_group(
                "sub",
                relation="and",
                rules=[
                    _single_rule("exclude", ["北大"]),
                    _single_rule("exclude", ["北京大学"]),
                ],
            )
        ],
    )
    terms = _runtime_terms(query_parts)
    bool_queries = list(_collect_bool_queries(query_parts.query))

    assert any(bool_query.get("must_not") == terms for bool_query in bool_queries)
    assert not any({"bool": {"must": terms}} in bool_query.get("must_not", []) for bool_query in bool_queries)


def test_sub_channel_or_excludes_negates_any_matching_exclude_condition():
    svc = ArticleEsService()

    query_parts = svc._build_count_query_parts(
        source_ids=["s1"],
        filter_rules=[
            _rule_group(
                "sub",
                relation="or",
                rules=[
                    _single_rule("exclude", ["北大"]),
                    _single_rule("exclude", ["北京大学"]),
                ],
            )
        ],
    )
    terms = _runtime_terms(query_parts)
    expected_should = [{"bool": {"must_not": [{"bool": {"should": terms, "minimum_should_match": 1}}]}}]
    bool_queries = list(_collect_bool_queries(query_parts.query))

    assert any(bool_query.get("should") == expected_should for bool_query in bool_queries)
    assert not any(
        bool_query.get("should") == [{"bool": {"must_not": [term]}} for term in terms] for bool_query in bool_queries
    )


def test_sub_channel_and_mixed_include_exclude_combines_must_and_must_not():
    svc = ArticleEsService()

    query_parts = svc._build_count_query_parts(
        source_ids=["s1"],
        filter_rules=[
            _rule_group(
                "sub",
                relation="and",
                rules=[
                    _single_rule("include", ["北大"]),
                    _single_rule("exclude", ["北京大学"]),
                ],
            )
        ],
    )
    include_term, exclude_term = _runtime_terms(query_parts)
    bool_queries = list(_collect_bool_queries(query_parts.query))

    assert any(
        bool_query.get("must") == [include_term] and bool_query.get("must_not") == [exclude_term]
        for bool_query in bool_queries
    )


def test_sub_channel_or_mixed_include_exclude_combines_should_conditions():
    svc = ArticleEsService()

    query_parts = svc._build_count_query_parts(
        source_ids=["s1"],
        filter_rules=[
            _rule_group(
                "sub",
                relation="or",
                rules=[
                    _single_rule("include", ["北大"]),
                    _single_rule("exclude", ["北京大学"]),
                ],
            )
        ],
    )
    include_term, exclude_term = _runtime_terms(query_parts)
    expected_should = [
        include_term,
        {"bool": {"must_not": [{"bool": {"should": [exclude_term], "minimum_should_match": 1}}]}},
    ]
    bool_queries = list(_collect_bool_queries(query_parts.query))

    assert any(bool_query.get("should") == expected_should for bool_query in bool_queries)


@pytest.mark.asyncio
async def test_count_articles_uses_search_for_sub_channel_runtime_mapping():
    svc = ArticleEsService()
    client = AsyncMock()
    client.search.return_value = {"hits": {"total": {"value": 3, "relation": "eq"}, "hits": []}}
    svc._get_client = AsyncMock(return_value=client)

    count = await svc.count_articles(source_ids=["s1"], filter_rules=[_rule_group("sub")])

    assert count == 3
    client.count.assert_not_called()
    client.search.assert_awaited_once()
    search_body = client.search.await_args.kwargs["body"]
    assert search_body["size"] == 0
    assert search_body["track_total_hits"] is True
    assert search_body["runtime_mappings"]


@pytest.mark.asyncio
async def test_count_articles_keeps_count_api_for_main_channel_rules():
    svc = ArticleEsService()
    client = AsyncMock()
    client.count.return_value = {"count": 5}
    svc._get_client = AsyncMock(return_value=client)

    count = await svc.count_articles(source_ids=["s1"], filter_rules=[_rule_group("main")])

    assert count == 5
    client.count.assert_awaited_once()
    client.search.assert_not_called()


@pytest.mark.asyncio
async def test_search_articles_carries_runtime_mapping_only_for_sub_rules():
    svc = ArticleEsService()
    client = AsyncMock()
    client.search.return_value = {"hits": {"total": {"value": 0, "relation": "eq"}, "hits": []}}
    svc._get_client = AsyncMock(return_value=client)

    await svc.search_articles(source_ids=["s1"], filter_rules=[_rule_group("sub")], page=1, page_size=20)

    search_body = client.search.await_args.kwargs["body"]
    assert search_body["runtime_mappings"]
    assert "match_phrase" not in json.dumps(search_body["query"], ensure_ascii=False)


@pytest.mark.asyncio
async def test_count_articles_batch_carries_runtime_mapping_per_sub_request():
    svc = ArticleEsService()
    client = AsyncMock()
    client.msearch.return_value = {
        "responses": [
            {"hits": {"total": {"value": 1, "relation": "eq"}}},
            {"hits": {"total": {"value": 2, "relation": "eq"}}},
        ]
    }
    svc._get_client = AsyncMock(return_value=client)

    counts = await svc.count_articles_batch(
        [
            {"source_ids": ["s1"], "filter_rules": [_rule_group("sub")]},
            {"source_ids": ["s1"], "filter_rules": [_rule_group("main")]},
        ]
    )

    assert counts == [1, 2]
    body = client.msearch.await_args.kwargs["body"]
    assert body[1]["runtime_mappings"]
    assert "runtime_mappings" not in body[3]


def test_match_article_ids_sync_carries_runtime_mapping_for_sub_rules(monkeypatch):
    svc = ArticleEsService()
    captured_body = {}

    class FakeSyncClient:
        def search(self, *, index, body):
            captured_body.update(body)
            return {"hits": {"hits": [{"_id": "a1"}]}}

    monkeypatch.setattr(article_es_service_module, "get_es_connection_sync", lambda: FakeSyncClient())

    matched_ids = svc.match_article_ids_sync(
        article_ids=["a1", "a2"],
        source_ids=["s1"],
        filter_rules=[_rule_group("sub", rule_type="include")],
    )

    assert matched_ids == ["a1"]
    assert captured_body["runtime_mappings"]
