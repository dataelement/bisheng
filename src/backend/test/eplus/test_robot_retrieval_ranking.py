"""Unified ranking must not compare arbitrary provider scores across spaces."""

from langchain_core.documents import Document

from bisheng.eplus.domain.services.retrieval_ranking import rank_robot_candidates, trim_robot_candidates


def _doc(fid, text, rank=1, name="文档.pdf"):
    return Document(
        page_content=text,
        metadata={"document_id": fid, "document_name": name, "knowledge_id": fid, "robot_recall_rank": rank},
    )


def test_global_keyword_match_outranks_unrelated_local_top_hit():
    docs = [_doc(1, "发票金额", 1), _doc(2, "深圳市医学研究项目申请", 4)]
    result = rank_robot_candidates(docs, "深圳市医学研究")
    assert [d.metadata["document_id"] for d in result] == [2, 1]


def test_provider_raw_scores_cannot_reverse_the_ranking():
    docs = [_doc(1, "发票金额"), _doc(2, "医学研究")]
    docs[0].metadata["score"] = 1000000
    docs[1].metadata["score"] = -1000000
    assert rank_robot_candidates(docs, "医学研究")[0].metadata["document_id"] == 2


def test_filename_is_part_of_global_keyword_matching():
    docs = [_doc(1, "普通正文"), _doc(2, "项目办理办法", name="深圳市医学研究申请指南.pdf")]
    assert rank_robot_candidates(docs, "深圳市医学研究")[0].metadata["document_id"] == 2


def test_stale_ingestion_title_does_not_affect_ranking_or_use_body_budget():
    docs = [
        _doc(1, "{<file_title>医学研究</file_title><paragraph_content>发票金额</paragraph_content>}"),
        _doc(2, "{<file_title>旧名字</file_title><paragraph_content>医学研究正文</paragraph_content>}"),
    ]
    result = trim_robot_candidates(rank_robot_candidates(docs, "医学研究"), 5)
    assert result[0].metadata["document_id"] == 2
    assert result[0].page_content == "医学研究正"


def test_binding_iteration_order_does_not_change_tied_ranking():
    docs = [_doc(2, "same"), _doc(1, "same")]
    assert [d.metadata["document_id"] for d in rank_robot_candidates(docs, "other")] == [1, 2]
    assert [d.metadata["document_id"] for d in rank_robot_candidates(docs[::-1], "other")] == [1, 2]


def test_trim_does_not_mutate_retrieval_candidates_or_overrun_budget():
    doc = _doc(1, "abcdef")
    assert trim_robot_candidates([doc], 0) == []
    result = trim_robot_candidates([doc], 3)
    assert result[0].page_content == "abc"
    assert result[0].metadata["content_truncated"] is True
    assert doc.page_content == "abcdef"
    assert "content_truncated" not in doc.metadata
