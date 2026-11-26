"""Words of the memory keyword search (keyword_terms.py, design decision 12)."""

import pytest

from bisheng.memory.domain.services.keyword_terms import MEMORY_STOPWORDS, phrase_query, query_terms


@pytest.mark.parametrize(
    ("query", "terms"),
    [
        # 116, 2026-11-25: these found an unrelated item through "用户" or "出".
        ("用户旅行偏好 出行习惯", ["旅行", "出行"]),
        ("帮我规划一个日本旅游行程", ["规划", "日本", "旅游", "行程"]),
        ("台湾旅游 偏好", ["台湾", "旅游"]),
        # The words that name the topic stay.
        ("用户要求调用技能生成用例", ["调用", "技能", "生成", "用例"]),
        ("用户喜欢用表格总结", ["表格", "总结"]),
        ("What does the user prefer for reports", ["reports"]),
        ("JSON 输出格式", ["json", "输出", "格式"]),
    ],
)
def test_query_terms(query, terms):
    assert query_terms(query) == terms


@pytest.mark.parametrize("query", ["", "\uff0c\u3002\uff01", "用户喜欢什么", "我的偏好是"])
def test_query_without_topic_words_has_no_terms(query):
    assert query_terms(query) == []


def test_terms_are_distinct_and_keep_query_order():
    assert query_terms("旅游 日本 旅游") == ["旅游", "日本"]


def test_memory_stopwords_hold_the_writing_template_words():
    assert {"用户", "喜欢", "偏好", "通常", "习惯"} <= MEMORY_STOPWORDS


def test_phrase_query_keeps_the_field_and_the_filter():
    flt = [{"term": {"metadata.user_id": 3}}]
    body = {"query": {"bool": {"must": [{"match": {"text": {"query": "x"}}}], "filter": flt}}}
    out = phrase_query(["日本", "旅游"])(body, "x")
    assert out["query"] == {
        "bool": {
            "should": [{"match_phrase": {"text": "日本"}}, {"match_phrase": {"text": "旅游"}}],
            "minimum_should_match": 1,
            "filter": flt,
        }
    }
