"""Selection fairness, actual-body budget and trustworthy source projection."""

import json

import pytest
from langchain_core.documents import Document

from bisheng.common.errcode.knowledge import KnowledgeAnswerRetrievalError
from bisheng.knowledge.domain.services.knowledge_answer_context import build_answer_context


def doc(text, file=11, index=0, **metadata):
    return Document(
        page_content=text, metadata={"document_id": file, "chunk_index": index, "document_name": "file.txt", **metadata}
    )


def test_round_robin_independent_of_scope_order():
    sources = {2: [doc("b0", 22), doc("b1", 22, 1)], 1: [doc("a0"), doc("a1", index=1)]}
    first = build_answer_context(sources, top_k=3, max_content=100)
    assert first == build_answer_context(dict(reversed(list(sources.items()))), top_k=3, max_content=100)
    chunks = json.loads(first[0])["reference_chunks"]
    assert [(c["knowledge_id"], c["content"]) for c in chunks] == [(1, "a0"), (2, "b0"), (1, "a1")]
    assert [(r.knowledge_id, r.document_id) for r in first[1]] == [(1, 11), (2, 22)]


def test_body_budget_truncation_and_only_actual_references():
    context, refs = build_answer_context(
        {1: [doc(" abc "), doc("unused", 99)], 2: [doc("defgh", 22)]}, top_k=50, max_content=5
    )
    chunks = json.loads(context)["reference_chunks"]
    assert [c["content"] for c in chunks] == ["abc", "de"]
    assert [c["truncated"] for c in chunks] == [False, True]
    assert sum(len(c["content"]) for c in chunks) == 5
    assert [r.document_id for r in refs] == [11, 22]
    assert all(r.document_update_time == "" for r in refs)


def test_chunk_dedup_and_space_file_identity():
    context, refs = build_answer_context(
        {1: [doc("first"), doc("duplicate"), doc("next", index=1)], 2: [doc("same file ID")]}, top_k=50, max_content=100
    )
    assert [c["content"] for c in json.loads(context)["reference_chunks"]] == ["first", "same file ID", "next"]
    assert [(r.knowledge_id, r.document_id) for r in refs] == [(1, 11), (2, 11)]


def test_whitespace_without_source_is_empty():
    assert build_answer_context({1: [Document(page_content=" \n")]}, top_k=1, max_content=1) == ("", [])


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"document_id": 1},
        {"document_id": 0, "chunk_index": 0},
        {"document_id": True, "chunk_index": 0},
        {"document_id": 1, "chunk_index": -1},
        {"document_id": 1, "chunk_index": True},
        {"document_id": 1.5, "chunk_index": 0},
        {"document_id": "bad", "chunk_index": 0},
    ],
)
def test_nonempty_unidentified_content_fails_closed(metadata):
    with pytest.raises(KnowledgeAnswerRetrievalError):
        build_answer_context({1: [Document(page_content="content", metadata=metadata)]}, top_k=1, max_content=100)


def test_legacy_string_source_ids_and_metadata_projection():
    _, refs = build_answer_context(
        {1: [doc("body", "7", "0", document_update_time="2026-10-08", path="private", download_url="secret")]},
        top_k=1,
        max_content=10,
    )
    assert refs[0].model_dump() == {
        "knowledge_id": 1,
        "document_id": 7,
        "document_name": "file.txt",
        "document_update_time": "2026-10-08",
    }
