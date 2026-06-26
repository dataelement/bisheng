"""TF-IDF cosine utilities for refined content-similarity scoring.

SimHash gives a coarse 64-bit fingerprint match that can report ~100% for
documents that merely share a template/structure but differ in substance.
This module re-scores already-simhash-matched candidates with a TF-IDF cosine
over a *local corpus* (the current file + its candidate set), which keys on the
actual terms instead of a structural fingerprint and filters out such false
positives.

Pure-Python (collections + math) so it adds no new dependency; tokenization
reuses jieba to stay consistent with the simhash pipeline.

Tokenization (the jieba step — by far the hottest part) recurs across many
recommendation requests for the same candidate documents, so callers memoize
it externally (the version service caches token lists in Redis keyed on a
content fingerprint). This module stays pure/stateless.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable, Sequence

import jieba

# Drop pure punctuation/whitespace and bare numbers — they carry no topical
# signal and only dilute the cosine. Single CJK chars are kept (meaningful).
_PUNCT_OR_SPACE = re.compile(r"^[\s\W_]+$", re.UNICODE)
_PURE_NUMBER = re.compile(r"^\d+(?:[.,]\d+)*$")


def tokenize(text: str) -> list[str]:
    """jieba-tokenize *text* into topical terms (lowercased, noise dropped)."""
    text = (text or "").strip()
    if not text:
        return []
    tokens: list[str] = []
    for tok in jieba.lcut(text):
        tok = tok.strip().lower()
        if not tok:
            continue
        if _PUNCT_OR_SPACE.match(tok) or _PURE_NUMBER.match(tok):
            continue
        tokens.append(tok)
    return tokens


# --- TF-IDF cosine ----------------------------------------------------------
def _tfidf_vector(tf: Counter, idf: dict[str, float]) -> dict[str, float]:
    """L2-normalized TF-IDF vector from a term-frequency counter."""
    total = sum(tf.values())
    if total == 0:
        return {}
    vec = {term: (count / total) * idf.get(term, 0.0) for term, count in tf.items()}
    norm = math.sqrt(sum(w * w for w in vec.values()))
    if norm == 0.0:
        return {}
    return {term: w / norm for term, w in vec.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine of two pre-L2-normalized sparse vectors (= their dot product)."""
    if not a or not b:
        return 0.0
    # Iterate the smaller vector for the dot product.
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(term, 0.0) for term, w in a.items())


def tfidf_cosine_scores_from_tokens(
    query_tokens: Sequence[str],
    candidate_tokens: Sequence[Sequence[str]],
) -> list[float]:
    """TF-IDF cosine of pre-tokenized *query_tokens* against each candidate.

    IDF is computed across the query + all candidates (the documents being
    compared) so the score reflects how distinctive the shared terms are within
    this specific comparison set. Returns one score in [0, 1] per candidate,
    in input order.
    """
    docs_tokens = [query_tokens, *candidate_tokens]
    n_docs = len(docs_tokens)

    # Document frequency over the local corpus.
    df: Counter = Counter()
    for toks in docs_tokens:
        df.update(set(toks))

    # Smoothed IDF: ln((1 + N) / (1 + df)) + 1, always positive.
    idf = {term: math.log((1 + n_docs) / (1 + freq)) + 1.0 for term, freq in df.items()}

    query_vec = _tfidf_vector(Counter(query_tokens), idf)
    return [_cosine(query_vec, _tfidf_vector(Counter(toks), idf)) for toks in candidate_tokens]


def tfidf_cosine_scores(query_text: str, candidate_texts: Iterable[str]) -> list[float]:
    """Text-in convenience wrapper around :func:`tfidf_cosine_scores_from_tokens`.

    Tokenizes inline (no cache). Prefer the tokens variant with
    :func:`tokenize_cached` on hot paths. Empty texts score 0.0.
    """
    return tfidf_cosine_scores_from_tokens(
        tokenize(query_text), [tokenize(t) for t in candidate_texts]
    )
