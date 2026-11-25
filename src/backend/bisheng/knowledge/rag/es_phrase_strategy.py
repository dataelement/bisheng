"""BM25 search of knowledge chunks that ranks whole words above shared characters.

The chunk indices use the standard analyzer, which splits Chinese into single
characters. The default BM25 query is one ``match``: a chunk that shares any
character with the query is found, and its score adds up character by
character, so a chunk with the exact term "差旅报销" can rank below a long
chunk full of "差", "报" and "销". Relevant chunks then fall behind the
content limit after fusion and are cut off.

These strategies keep that ``match`` as the condition (the set of found chunks
does not change) and add one ``match_phrase`` per jieba word of the query as
an optional clause: a chunk that holds a word as consecutive characters gets
the score of that phrase on top. The index and its mapping stay as they are.
"""

from __future__ import annotations

from typing import Any

import jieba

from bisheng.common.utils.query_terms import query_terms
from bisheng.core.vectorstore import AsyncBM25Strategy, BM25Strategy

# A long question (workflows often pass the whole user message) must not build
# a query with hundreds of clauses.
MAX_PHRASE_TERMS = 16
DEFAULT_PHRASE_BOOST = 1.0

# es_query is synchronous and runs on the event loop; load the dictionary when
# the process imports this module, not on the first search.
jieba.initialize()


def add_phrase_boost(body: dict[str, Any], query: str | None, text_field: str, boost: float) -> dict[str, Any]:
    """Add one optional ``match_phrase`` per word of ``query`` to a BM25 body."""
    terms = query_terms(query or "", max_terms=MAX_PHRASE_TERMS)
    if not terms:
        return body
    body["query"]["bool"]["should"] = [
        {"match_phrase": {text_field: {"query": term, "boost": boost}}} for term in terms
    ]
    return body


class PhraseBoostBM25Strategy(BM25Strategy):
    def __init__(self, boost: float = DEFAULT_PHRASE_BOOST, **kwargs: Any):
        super().__init__(**kwargs)
        self.boost = boost

    def es_query(self, *, query, text_field, **kwargs) -> dict[str, Any]:
        body = super().es_query(query=query, text_field=text_field, **kwargs)
        return add_phrase_boost(body, query, text_field, self.boost)


class AsyncPhraseBoostBM25Strategy(AsyncBM25Strategy):
    def __init__(self, boost: float = DEFAULT_PHRASE_BOOST, **kwargs: Any):
        super().__init__(**kwargs)
        self.boost = boost

    def es_query(self, *, query, text_field, **kwargs) -> dict[str, Any]:
        body = super().es_query(query=query, text_field=text_field, **kwargs)
        return add_phrase_boost(body, query, text_field, self.boost)
