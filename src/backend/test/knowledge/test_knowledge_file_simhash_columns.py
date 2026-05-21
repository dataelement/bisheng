"""Regression tests for the new simhash / similar_status columns on KnowledgeFile."""
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


def test_knowledge_file_has_simhash_field():
    kf = KnowledgeFile(knowledge_id=1, file_name="a.pdf")
    assert hasattr(kf, "simhash")
    assert kf.simhash is None


def test_knowledge_file_simhash_accepts_hex():
    kf = KnowledgeFile(knowledge_id=1, file_name="a.pdf", simhash="0123456789abcdef")
    assert kf.simhash == "0123456789abcdef"


def test_knowledge_file_has_similar_status_default_zero():
    kf = KnowledgeFile(knowledge_id=1, file_name="a.pdf")
    assert kf.similar_status == 0


def test_knowledge_file_similar_status_accepts_states():
    for state in (0, 1, 2):
        kf = KnowledgeFile(knowledge_id=1, file_name="a.pdf", similar_status=state)
        assert kf.similar_status == state
