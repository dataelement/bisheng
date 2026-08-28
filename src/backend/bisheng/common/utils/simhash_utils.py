"""SimHash utilities for content similarity detection."""
from simhash import Simhash

import jieba


def compute_simhash_64_hex(text: str) -> str:
    """Compute a 64-bit SimHash of *text*, return as 16-char lowercase hex.

    Uses jieba for CJK-aware tokenization. Empty/whitespace text produces "0" * 16.

    jieba.lcut splits Latin-script runs word-by-word but emits every space
    character between them as its own token (e.g. "The quick brown" ->
    ["The", " ", "quick", " ", "brown"]). Simhash() takes an unweighted list,
    so a repeated token's hash gets counted once per occurrence — in English/
    code/config-heavy text, space tokens can be close to half the list,
    letting that single low-information token's hash dominate the bit vote
    and drown out the real content. Two unrelated documents with a similar
    word/space ratio can then converge on the same or a near-identical
    fingerprint regardless of what they actually say (verified: two
    unrelated English sentences hashed identically before this filter, and
    diverged to 58% similarity after it). Dropping whitespace-only tokens
    removes that dominant no-signal feature without changing behavior for
    CJK-only text (jieba doesn't emit space tokens between CJK characters).
    """
    text = (text or "").strip()
    if not text:
        return "0" * 16
    tokens = [token for token in jieba.lcut(text) if token.strip()]
    sh = Simhash(tokens, f=64)
    return f"{sh.value:016x}"


def hamming_distance(hex_a: str, hex_b: str) -> int:
    """Hamming distance between two 16-char hex simhashes (64 bits)."""
    a = int(hex_a, 16)
    b = int(hex_b, 16)
    return bin(a ^ b).count("1")


def similarity(hex_a: str, hex_b: str) -> float:
    """Similarity = 1 - hamming/64. Range [0, 1]."""
    return 1.0 - hamming_distance(hex_a, hex_b) / 64.0
