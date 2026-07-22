from __future__ import annotations

from types import SimpleNamespace

import scripts.remove_industry_intelligence_tag_mismatch as script
from scripts.remove_industry_intelligence_tag_mismatch import (
    should_remove_tag_for_file,
)


def test_should_remove_tag_for_file_keeps_new_category():
    assert should_remove_tag_for_file("NEW", target_category_code="NEW") is False
    assert should_remove_tag_for_file("new", target_category_code="NEW") is False


def test_should_remove_tag_for_file_removes_other_categories():
    assert should_remove_tag_for_file("STD", target_category_code="NEW") is True
    assert should_remove_tag_for_file("RPT", target_category_code="NEW") is True


def test_should_remove_tag_for_file_removes_missing_category():
    assert should_remove_tag_for_file(None, target_category_code="NEW") is True
    assert should_remove_tag_for_file("", target_category_code="NEW") is True


def test_resolve_file_category_code_from_split_rule_and_encoding():
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

    split_rule_file = KnowledgeFile(
        id=1,
        split_rule='{"file_category_code": "STD", "business_domain_code": "PP"}',
    )
    assert script.resolve_file_category_code(split_rule_file) == "STD"

    encoding_file = KnowledgeFile(id=2, file_encoding="SGGF-NEW-PP-20260700000001")
    assert script.resolve_file_category_code(encoding_file) == "NEW"


def test_build_candidate_marks_orphan_links():
    candidate, action = script._build_candidate(
        link_id=10,
        file_id=99,
        db_file=None,
        target_category_code="NEW",
    )
    assert candidate is None
    assert action == "orphan"


def test_build_candidate_keeps_new_files():
    db_file = SimpleNamespace(
        file_name="趋势.pdf",
        knowledge_id=12,
        tenant_id=1,
        split_rule='{"file_category_code": "NEW"}',
        file_encoding=None,
    )
    candidate, action = script._build_candidate(
        link_id=11,
        file_id=100,
        db_file=db_file,
        target_category_code="NEW",
    )
    assert action == "keep"
    assert candidate is not None
    assert candidate.category_code == "NEW"
