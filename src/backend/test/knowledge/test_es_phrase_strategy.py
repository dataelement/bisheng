"""Knowledge ES search: whole query words rank above shared characters."""

import pytest

from bisheng.common.utils.query_terms import query_terms
from bisheng.core.vectorstore import AsyncBM25Strategy, BM25Strategy
from bisheng.knowledge.rag import es_phrase_strategy
from bisheng.knowledge.rag.es_phrase_strategy import (
    MAX_PHRASE_TERMS,
    AsyncPhraseBoostBM25Strategy,
    PhraseBoostBM25Strategy,
)

STRATEGIES = [PhraseBoostBM25Strategy, AsyncPhraseBoostBM25Strategy]
FILTER = [{"terms": {"metadata.document_id": [1, 2]}}]


def _body(strategy, query):
    return strategy.es_query(
        query=query, query_vector=None, text_field="text", vector_field="vector", k=10, num_candidates=10, filter=FILTER
    )


@pytest.mark.parametrize("cls", STRATEGIES)
def test_keeps_match_and_filter_and_adds_phrases(cls):
    body = _body(cls(), "请问差旅报销标准是什么")
    bool_query = body["query"]["bool"]
    assert bool_query["must"] == [{"match": {"text": {"query": "请问差旅报销标准是什么"}}}]
    assert bool_query["filter"] == FILTER
    phrases = [c["match_phrase"]["text"]["query"] for c in bool_query["should"]]
    assert phrases == ["差旅", "报销", "标准"]
    assert "minimum_should_match" not in bool_query


@pytest.mark.parametrize("cls", STRATEGIES)
def test_boost_is_applied(cls):
    body = _body(cls(boost=2.0), "差旅报销")
    assert {c["match_phrase"]["text"]["boost"] for c in body["query"]["bool"]["should"]} == {2.0}


@pytest.mark.parametrize(
    "cls,base", [(PhraseBoostBM25Strategy, BM25Strategy), (AsyncPhraseBoostBM25Strategy, AsyncBM25Strategy)]
)
def test_query_without_words_keeps_the_plain_body(cls, base):
    plain = _body(base(), "我 的？")
    assert _body(cls(), "我 的？") == plain


@pytest.mark.parametrize("cls", STRATEGIES)
def test_long_query_is_capped(cls):
    query = "，".join(f"项目{i}编号AB{i:03d}" for i in range(40))
    should = _body(cls(), query)["query"]["bool"]["should"]
    assert len(should) == MAX_PHRASE_TERMS


@pytest.mark.parametrize(
    "cls,base", [(PhraseBoostBM25Strategy, BM25Strategy), (AsyncPhraseBoostBM25Strategy, AsyncBM25Strategy)]
)
def test_mapping_is_unchanged(cls, base):
    kwargs = {"text_field": "text", "vector_field": "vector", "num_dimensions": None}
    assert cls().es_mappings_settings(**kwargs) == base().es_mappings_settings(**kwargs)


def test_knowledge_words_keep_memory_domain_words():
    # "用户" and "偏好" are memory stopwords, but they can be the topic of a document.
    assert query_terms("用户偏好设置") == ["用户", "偏好", "设置"]


def test_knowledge_store_uses_the_phrase_strategy(monkeypatch):
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
    from bisheng.knowledge.rag.elasticsearch_factory import ElasticsearchFactory

    seen = {}
    monkeypatch.setattr(ElasticsearchFactory, "init_vectorstore", lambda name, **kw: seen.setdefault("async", kw))
    monkeypatch.setattr(ElasticsearchFactory, "init_vectorstore_sync", lambda name, **kw: seen.setdefault("sync", kw))
    KnowledgeRag.init_es_vectorstore("col_1")
    KnowledgeRag.init_es_vectorstore_sync("col_1")
    assert isinstance(seen["async"]["strategy"], AsyncPhraseBoostBM25Strategy)
    assert isinstance(seen["sync"]["strategy"], PhraseBoostBM25Strategy)


def test_memory_store_keeps_the_plain_strategy(monkeypatch):
    from bisheng.knowledge.rag.elasticsearch_factory import ElasticsearchFactory
    from bisheng.memory.domain.services import index

    seen = {}
    monkeypatch.setattr(ElasticsearchFactory, "init_vectorstore", lambda name, **kw: seen.setdefault("kw", kw))
    index._es_store()
    assert "strategy" not in seen["kw"]


def test_module_preloads_the_dictionary():
    assert es_phrase_strategy.jieba.dt.initialized
