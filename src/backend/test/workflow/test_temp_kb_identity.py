"""F062 T008 — per-file UUID identity, retriever collection, bbox isolation.

The identity factory and collector are tiny pure helpers so this file does
not need a running InputNode / Milvus.
"""

from langchain_core.documents import Document

from bisheng.workflow.common.knowledge import RagUtils
from bisheng.workflow.nodes.input.input import InputNode, ParseModeEnum


def test_temp_file_identity_is_unique_per_call_and_has_no_bbox_keys():
    first = InputNode.temp_file_identity_metadata("a.pdf", "wf-1")
    second = InputNode.temp_file_identity_metadata("b.pdf", "wf-1")
    assert first["document_id"] != second["document_id"]
    assert first["document_name"] == "a.pdf"
    assert first["knowledge_id"] == "wf-1"
    for key in ("bbox", "page", "chunk_index"):
        assert key not in first
        assert key not in second


def test_collect_temp_document_ids_reads_every_file_not_just_first():
    metadatas = [
        [{"document_id": "id-a", "document_name": "a.pdf"}],
        [
            {"document_id": "id-b", "document_name": "b.pdf"},
            {"document_id": "id-c", "document_name": "c.pdf"},
        ],
    ]
    assert RagUtils.collect_temp_document_ids(metadatas) == ["id-a", "id-b", "id-c"]


def test_file_level_identity_update_does_not_wipe_pipeline_bbox():
    identity = InputNode.temp_file_identity_metadata("a.pdf", "wf-1")
    chunk = {"page_content": "hello", "bbox": "[[1,2,3,4]]", "page": 2, "chunk_index": 0}
    chunk.update(identity)
    assert chunk["bbox"] == "[[1,2,3,4]]"
    assert chunk["page"] == 2
    assert chunk["chunk_index"] == 0
    assert chunk["document_name"] == "a.pdf"


def test_backfill_stamps_source_url_by_document_id():
    docs = [
        Document(page_content="a", metadata={"document_id": "id-a"}),
        Document(page_content="b", metadata={"document_id": "id-b"}),
    ]
    RagUtils.backfill_temp_source_paths(docs, {"id-a": "https://minio/a.pdf", "id-b": "https://minio/b.pdf"})
    assert docs[0].metadata["source_url"] == "https://minio/a.pdf"
    assert docs[1].metadata["source_url"] == "https://minio/b.pdf"


def test_parse_only_and_keep_raw_do_not_expose_temp_kb_key():
    node = InputNode.__new__(InputNode)
    node._current_v = 2
    node.node_data = type("_ND", (), {"v": 3})()
    key_info = {
        "key": "k",
        "file_content": "c",
        "file_path": "p",
        "image_file": "img",
        "file_type": "file",
        "file_parse_mode": ParseModeEnum.EXTRACT_TEXT.value,
    }
    key_value = {"c": "text", "p": ["minio/p"], "img": [], "k": [{"document_name": "a"}]}
    exposed = set(node._parse_upload_file_variables(key_info, key_value))
    assert "k" not in exposed

    key_info["file_parse_mode"] = ParseModeEnum.KEEP_RAW.value
    exposed_raw = set(node._parse_upload_file_variables(key_info, key_value))
    assert "k" not in exposed_raw
