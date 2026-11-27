"""Words of a keyword search over a per-character Chinese index.

The ES indices of knowledge chunks and memory items use the standard analyzer:
Chinese text becomes single characters, and a plain ``match`` finds a document
that shares any one character with the query. Searches cut the query into words
with jieba and ask for each word as consecutive characters (``match_phrase``);
the indices stay as they are.

General stopwords (function words and the phrasing of a request) and
single-character words are left out: they say nothing about the topic, and a
single character matches too much on a per-character index. A caller adds the
stopwords of its own domain with ``extra_stopwords``.
"""

from __future__ import annotations

import logging
import re

import jieba

jieba.setLogLevel(logging.WARNING)

GENERAL_STOPWORDS = frozenset(
    {
        # pronouns and determiners
        "我们",
        "你们",
        "他们",
        "她们",
        "它们",
        "自己",
        "大家",
        "这个",
        "那个",
        "这些",
        "那些",
        "这样",
        "那样",
        "这么",
        "那么",
        "这里",
        "那里",
        "一个",
        "一些",
        "一种",
        "一下",
        "一点",
        "其中",
        "某个",
        "各种",
        "所有",
        "任何",
        "每个",
        # question words
        "什么",
        "怎么",
        "怎样",
        "如何",
        "为什么",
        "哪些",
        "哪个",
        "哪里",
        "是否",
        "是不是",
        "有没有",
        # conjunctions, prepositions, adverbs
        "以及",
        "或者",
        "还是",
        "而且",
        "并且",
        "但是",
        "不过",
        "因为",
        "所以",
        "如果",
        "虽然",
        "然后",
        "关于",
        "对于",
        "根据",
        "通过",
        "按照",
        "除了",
        "已经",
        "正在",
        "现在",
        "之前",
        "之后",
        "以后",
        "时候",
        "可以",
        "可能",
        "能够",
        "应该",
        "比较",
        "非常",
        "特别",
        "还有",
        "就是",
        "只是",
        "也是",
        "都是",
        "没有",
        "不是",
        # the phrasing of a request
        "帮我",
        "帮忙",
        "请问",
        "麻烦",
        "给我",
        "告诉",
        "一下子",
        # English function words
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "what",
        "how",
        "does",
        "are",
        "was",
        "you",
        "your",
        "about",
        "from",
        "into",
        "please",
    }
)

# A word must hold a letter, a digit or a CJK character (drops punctuation).
_WORD = re.compile(r"[0-9A-Za-z\u4e00-\u9fff]")


def query_terms(query: str, extra_stopwords: frozenset[str] = frozenset(), max_terms: int | None = None) -> list[str]:
    """Distinct words of ``query`` to search for, in query order; may be empty.

    The first call loads the jieba dictionary (about one second).
    """
    terms: list[str] = []
    for word in jieba.cut_for_search(query or ""):
        word = word.strip().lower()
        if len(word) < 2 or word in GENERAL_STOPWORDS or word in extra_stopwords or not _WORD.search(word):
            continue
        if word not in terms:
            terms.append(word)
            if max_terms is not None and len(terms) >= max_terms:
                break
    return terms
