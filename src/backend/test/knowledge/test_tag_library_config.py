"""Tests for the tag_library config schema in KnowledgeConf."""
from bisheng.core.config.settings import KnowledgeConf, TagLibraryConf


def test_tag_library_default_values():
    conf = KnowledgeConf()
    assert conf.tag_library.review_tag_similarity_threshold == 0.85


def test_tag_library_explicit_values():
    conf = KnowledgeConf(tag_library={"review_tag_similarity_threshold": 0.9})
    assert conf.tag_library.review_tag_similarity_threshold == 0.9


def test_tag_library_conf_standalone():
    tag_library = TagLibraryConf()
    assert tag_library.review_tag_similarity_threshold == 0.85
