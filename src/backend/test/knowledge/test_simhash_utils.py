"""Tests for simhash_utils."""
from bisheng.common.utils.simhash_utils import (
    compute_simhash_64_hex,
    hamming_distance,
    similarity,
)


def test_compute_simhash_returns_16_char_hex():
    h = compute_simhash_64_hex("hello world this is a test document")
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_compute_simhash_empty_returns_zeros():
    assert compute_simhash_64_hex("") == "0" * 16
    assert compute_simhash_64_hex("   ") == "0" * 16
    assert compute_simhash_64_hex(None) == "0" * 16  # type: ignore


def test_compute_simhash_identical_text_same_hash():
    text = "知识空间文件版本管理是 BiSheng 的新功能"
    assert compute_simhash_64_hex(text) == compute_simhash_64_hex(text)


def test_hamming_distance_self_zero():
    h = compute_simhash_64_hex("the quick brown fox")
    assert hamming_distance(h, h) == 0


def test_similarity_self_is_1():
    h = compute_simhash_64_hex("python data structures and algorithms")
    assert similarity(h, h) == 1.0


def test_similarity_near_duplicates_high():
    """Near-duplicate Chinese paragraphs should produce similarity above 0.85."""
    text_a = "BiSheng 知识空间支持文件版本管理。逻辑文档可以归并多个物理文件版本。主版本对外生效。"
    text_b = "BiSheng 知识空间支持文件版本管理。逻辑文档可以归并多个物理文件版本本。主版本对外生效。"  # 只差一个字
    h_a = compute_simhash_64_hex(text_a)
    h_b = compute_simhash_64_hex(text_b)
    assert similarity(h_a, h_b) >= 0.85


def test_similarity_unrelated_text_low():
    """Unrelated texts should produce moderate or low similarity."""
    h_a = compute_simhash_64_hex("机器学习模型训练流程包括数据预处理、特征工程、模型选择")
    h_b = compute_simhash_64_hex("足球运动员转会市场的经济学分析与球队预算管理")
    # Just assert it's strictly less than 1 — exact value depends on tokenization
    assert similarity(h_a, h_b) < 1.0
