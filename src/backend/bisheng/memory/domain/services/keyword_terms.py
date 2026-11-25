"""Words of a memory keyword search (design decision 12).

The ES index of memory items uses the standard analyzer: Chinese text becomes
single characters, and a plain ``match`` finds an item that shares any one
character with the query ("出行" finds every item with "出"). The search cuts
the query into words with jieba instead and asks for each word as consecutive
characters (``match_phrase``); the index stays as it is.

Two kinds of words are left out, because they say nothing about the topic:

* general stopwords: function words and the phrasing of a request;
* memory stopwords: the words items carry because of how they are written. An
  item is about the user and says what the user likes, wants or usually does
  (consolidation prompt), so "用户", "喜欢", "通常" are in most items.

Single-character words are left out too: they match too much on a per-character
index. The lists follow common practice (general list + domain list from the
writing template); replace the domain list with words of high document
frequency once real memory items can be counted.
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
# A word must hold a letter, a digit or a CJK character (drops punctuation).
_WORD = re.compile(r"[0-9A-Za-z一-鿿]")


def query_terms(query: str) -> list[str]:
    """Distinct words of ``query`` to search for, in query order; may be empty."""
    terms: list[str] = []
    for word in jieba.cut_for_search(query or ""):
        word = word.strip().lower()
        if len(word) < 2 or word in STOPWORDS or not _WORD.search(word):
            continue
        if word not in terms:
            terms.append(word)
    return terms


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
