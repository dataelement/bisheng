"""SimHash utilities for content similarity detection."""
from simhash import Simhash

import jieba


def compute_simhash_64_hex(text: str) -> str:
    """Compute a 64-bit SimHash of *text*, return as 16-char lowercase hex.

    Uses jieba for CJK-aware tokenization. Empty/whitespace text produces "0" * 16.
    """
    text = (text or "").strip()
    if not text:
        return "0" * 16
    tokens = jieba.lcut(text)
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
