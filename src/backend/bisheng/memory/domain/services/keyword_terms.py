"""Words of a memory keyword search (design decision 12).

The query is cut into words by ``bisheng.common.utils.query_terms``, which
leaves out general stopwords and single characters, and each word is asked as
a phrase. Memory items add their own stopwords: the words items carry because
of how they are written. An item is about the user and says what the user
likes, wants or usually does (consolidation prompt), so "用户", "喜欢", "通常"
are in most items. The domain list follows the writing template; replace it
with words of high document frequency once real memory items can be counted.
"""

from __future__ import annotations

from bisheng.common.utils.query_terms import GENERAL_STOPWORDS
from bisheng.common.utils.query_terms import query_terms as _query_terms

MEMORY_STOPWORDS = frozenset(
    {
        # who an item is about
        "用户",
        "本人",
        "用户本人",
        # what the user likes, wants or asks for
        "喜欢",
        "不喜欢",
        "偏好",
        "偏爱",
        "喜好",
        "倾向",
        "倾向于",
        "希望",
        "想要",
        "需要",
        "要求",
        "习惯",
        "认可",
        "期望",
        "希望能",
        # how often or how generally
        "通常",
        "一般",
        "经常",
        "总是",
        "一直",
        "平时",
        "每次",
        "默认",
        "今后",
        "以后都",
        # item types and generic nouns of the writing template
        "事实",
        "经验",
        "记忆",
        "信息",
        "内容",
        "方式",
        "相关",
        "情况",
        "方面",
        # English counterparts
        "user",
        "users",
        "prefer",
        "prefers",
        "preference",
        "preferences",
        "like",
        "likes",
        "want",
        "wants",
        "usually",
        "always",
        "often",
    }
)

STOPWORDS = GENERAL_STOPWORDS | MEMORY_STOPWORDS


def query_terms(query: str) -> list[str]:
    """Distinct words of ``query`` to search for, in query order; may be empty."""
    return _query_terms(query, extra_stopwords=MEMORY_STOPWORDS)


def phrase_query(terms: list[str]):
    """``custom_query`` for the ES store: any of ``terms`` as a phrase, same filter."""

    def build(body: dict, _query: str | None) -> dict:
        bool_query = body["query"]["bool"]
        (field,) = bool_query["must"][0]["match"]
        body["query"] = {
            "bool": {
                "should": [{"match_phrase": {field: term}} for term in terms],
                "minimum_should_match": 1,
                "filter": bool_query.get("filter") or [],
            }
        }
        return body

    return build
