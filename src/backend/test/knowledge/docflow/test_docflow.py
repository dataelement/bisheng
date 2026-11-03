"""Self-contained protocol/contract tests; no running middleware is needed."""

import importlib.util
import json
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from langchain_core.documents import Document

from bisheng.knowledge.docflow.client import DocFlowClient, DocFlowError, SubmissionUnknown
from bisheng.knowledge.docflow.converter import convert_results


def load_service(name):
    # Avoid the legacy services/__init__.py bootstrap that starts middleware.
    path = Path(__file__).parents[3] / "bisheng" / "knowledge" / "domain" / "services" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


Service = load_service("docflow_service").DocFlowService
Ingest = load_service("docflow_ingest").DocFlowIngest


class State:
    def __init__(self, tenant_id=1):
        self.tenant_id = tenant_id
        self.rows = {}
        self.artifacts = {}

    def read(self, key):
        return dict(self.rows.get(key, {}))

    def write(self, key, value, scope="parse"):
        self.rows[key] = dict(value)

    def load_artifact(self, name):
        return self.artifacts.get(name)

    def save_artifact(self, key, value):
        name = f"docflow/{self.tenant_id}/{key}.json"
        self.artifacts[name] = value
        return name

    @contextmanager
    def lease(self, *args, **kwargs):
        yield lambda: None

    @contextmanager
    def capacity(self, *args):
        yield lambda: None


@pytest.fixture
def config():
    DocFlowClient._tokens.clear()
    return {
        "url": "http://mk.test:8080",
        "host": "mk.test",
        "app_key": "test-ak",
        "app_secret": "test-as",
        "docflow_app_id": "test-doc-ak",
        "docflow_secret_code": "test-doc-as",
        "workspace_id": "workspace",
        "poll_timeout": 0.01,
        "poll_interval": 0.001,
    }


def response(data, status=200):
    return SimpleNamespace(status_code=status, json=lambda: data)


def test_token_protocol_and_upload_fdid(config, tmp_path):
    DocFlowClient._tokens.clear()
    session = Mock()
    session.headers = {}
    session.post.side_effect = [
        response({"errcode": 0, "access_token": "secret-token", "expires_in": 7200}),
        response({"success": True, "data": {"fdId": "attachment"}}),
    ]
    client = DocFlowClient(config, session=session)
    client.authenticate()
    request = session.post.call_args.kwargs
    assert json.loads(request["data"]) == {"appKey": "test-ak", "appSecret": "test-as"}
    assert request["headers"]["Host"] == "mk.test"
    assert session.trust_env is False
    path = tmp_path / "sample.png"
    path.write_bytes(b"original image bytes")
    assert client.upload(path) == "attachment"
    assert session.post.call_args.args[0].endswith("/openapi/sys-attach/fileStream/upload")
    assert "Authorization" not in session.post.call_args.kwargs["headers"]


def test_network_exception_does_not_disclose_secrets(config):
    session = Mock(headers={})
    session.post.side_effect = requests.ConnectionError("access_token=secret-token appSecret=test-as")
    client = DocFlowClient(config, session=session)
    with pytest.raises(DocFlowError) as error:
        client.authenticate()
    assert "secret-token" not in str(error.value)
    assert "test-as" not in str(error.value)


def test_submission_error_is_never_auto_retried(config):
    client = DocFlowClient(config, session=Mock(headers={}))
    client.invoke = Mock(side_effect=DocFlowError("network timeout"))
    with pytest.raises(SubmissionUnknown):
        client.submit("attachment")
    assert client.invoke.call_count == 1


def file_result(lines=None):
    return {
        "id": "remote",
        "recognition_status": 1,
        "task_type": 1,
        "total_page_num": 1,
        "document": {
            "pages": [{"width": 200, "height": 100, "lines": lines or [{"text": "正文", "position": [0, 0, 60, 20]}]}]
        },
    }


def remote_client():
    client = Mock()
    client.upload.return_value = "attachment"
    client.submit.return_value = {"files": [{"id": "remote"}]}
    client.fetch.return_value = [file_result()]
    return client


def test_preview_then_ingestion_reuses_raw_ocr(config, tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(b"source")
    state, client = State(), remote_client()
    first = Service(config, state, client).parse(path)
    assert Service(config, state, client).parse(path) == first
    assert client.upload.call_count == client.submit.call_count == client.fetch.call_count == 1


def test_timeout_resumes_existing_remote_task(config, tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(b"source")
    state, client = State(), remote_client()
    client.fetch.return_value = []
    with pytest.raises(DocFlowError, match="timed out"):
        Service(config, state, client).parse(path)
    client.fetch.return_value = [file_result()]
    Service(config, state, client).parse(path)
    assert client.upload.call_count == client.submit.call_count == 1


def test_unknown_submission_is_fail_closed_on_restart(config, tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(b"source")
    state, client = State(), remote_client()
    client.submit.side_effect = SubmissionUnknown("uncertain")
    for _ in range(2):
        with pytest.raises(SubmissionUnknown):
            Service(config, state, client).parse(path)
    assert client.submit.call_count == 1


def test_expired_artifact_refetches_without_upload(config, tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(b"source")
    state, client = State(), remote_client()
    Service(config, state, client).parse(path)
    state.artifacts.clear()
    Service(config, state, client).parse(path)
    assert client.submit.call_count == 1
    assert client.fetch.call_count == 2


def test_tenants_and_workspace_cannot_share_remote_results(config, tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(b"source")
    state, client = State(), remote_client()
    Service(config, state, client).parse(path)
    state.tenant_id = 2
    Service(config, state, client).parse(path)
    Service({**config, "workspace_id": "another"}, state, client).parse(path)
    assert client.submit.call_count == 3


@pytest.mark.parametrize("status,extra", [(2, {}), (10, {}), (1, {"child_files": [{"id": "child"}]})])
def test_incomplete_or_split_results_are_not_silently_ingested(config, tmp_path, status, extra):
    path = tmp_path / "a.png"
    path.write_bytes(b"source")
    client = remote_client()
    client.fetch.return_value = [{**file_result(), "recognition_status": status, **extra}]
    with pytest.raises(DocFlowError):
        Service(config, State(), client).parse(path)


def test_converter_maps_final_markdown_and_preserves_repeated_text():
    result = file_result(
        [
            {"text": "标题", "type": "title", "position": [0, 0, 100, 20]},
            {"text": "左边", "position": [0, 30, 50, 50]},
            {"text": "右边", "position": [100, 30, 150, 50]},
            {"text": "重复|内容", "position": [0, 60, 70, 80]},
            {"text": "重复|内容", "position": [100, 60, 170, 80]},
        ]
    )
    converted = convert_results([result])
    assert converted.text.startswith("# 标题")
    assert converted.text.count("重复\\|内容") == 2
    for span in converted.spans:
        assert converted.text[span["start"] : span["end"]] == span["text"]
    assert converted.spans[0]["start"] == 2


def test_converter_rejects_missing_pages_and_empty_success():
    with pytest.raises(DocFlowError, match="incomplete"):
        convert_results([{**file_result(), "total_page_num": 3}])
    with pytest.raises(DocFlowError, match="no recognized text"):
        convert_results([file_result([{"text": ""}])])


def test_two_wide_columns_read_down_before_across():
    lines = [{"text": f"left-{index}", "position": [0, index * 25, 200, index * 25 + 20]} for index in range(4)]
    lines += [{"text": f"right-{index}", "position": [300, index * 25, 500, index * 25 + 20]} for index in range(4)]
    converted = convert_results([file_result(lines)])
    assert converted.text.index("left-3") < converted.text.index("right-0")


def test_explicit_grid_generates_semantic_table_without_duplicate_ocr():
    result = file_result(
        [
            {"text": "甲", "position": [0, 0, 20, 20]},
            {"text": "乙", "position": [30, 0, 50, 20]},
            {"text": "甲", "position": [100, 60, 120, 80]},
        ]
    )
    result["data"] = {
        "tables": [
            {
                "rows": [
                    [
                        {"value": "甲", "position": [0, 0, 20, 20]},
                        {"value": "乙", "position": [30, 0, 50, 20]},
                    ]
                ]
            }
        ]
    }
    converted = convert_results([result])
    assert "| 甲 | 乙 |" in converted.text
    assert converted.text.count("甲") == 2
    assert converted.text.count("乙") == 1
    assert any(span["type"] == "Table" for span in converted.spans)
    assert all(converted.text[span["start"] : span["end"]] == span["text"] for span in converted.spans)


def test_heading_split_retains_source_mapping():
    from bisheng.knowledge.rag.pipeline.transformer.docflow_structure import DocFlowStructureSplitter

    converted = convert_results(
        [
            file_result(
                [
                    {"text": "标题一", "type": "title", "position": [0, 0, 80, 20]},
                    {"text": "第一段正文", "position": [0, 30, 80, 50]},
                    {"text": "标题二", "type": "title", "position": [0, 60, 80, 80]},
                    {"text": "第二段正文", "position": [0, 90, 80, 110]},
                ]
            )
        ]
    )
    metadata = {
        "indexes": [[span["start"], span["end"]] for span in converted.spans],
        "bboxes": [span["bbox"] for span in converted.spans],
        "pages": [span["page"] for span in converted.spans],
        "types": [span["type"] for span in converted.spans],
    }
    chunks = DocFlowStructureSplitter(chunk_size=100, chunk_overlap=0).transform_documents(
        [Document(page_content=converted.text, metadata=metadata)]
    )
    assert len(chunks) == 2
    assert chunks[0].metadata["nav_path"] == ["标题一"]
    assert chunks[1].metadata["nav_path"] == ["标题二"]
    assert chunks[0].metadata["chunk_bboxes"]
    assert chunks[1].metadata["chunk_bboxes"]


def test_loader_to_pipeline_preview_and_ingest_without_second_ocr(config, tmp_path, monkeypatch):
    from bisheng.knowledge.rag.pipeline.base import NormalPipeline
    from bisheng.knowledge.rag.pipeline.loader.docflow import DocFlowLoader
    from bisheng.knowledge.rag.pipeline.transformer.splitter import SplitterTransformer
    from bisheng.knowledge.rag.pipeline.types import PipelineConfig, PipelineStage

    path = tmp_path / "sample.png"
    path.write_bytes(b"image")
    state, client = State(), remote_client()
    parent = types.ModuleType("bisheng.knowledge.domain.services")
    parent.__path__ = []
    monkeypatch.setitem(sys.modules, parent.__name__, parent)
    state_module = types.ModuleType(parent.__name__ + ".docflow_state")
    state_module.DocFlowState = lambda tenant_id: state
    service_module = types.ModuleType(parent.__name__ + ".docflow_service")
    service_module.DocFlowService = lambda configuration, state: Service(configuration, state, client)
    monkeypatch.setitem(sys.modules, state_module.__name__, state_module)
    monkeypatch.setitem(sys.modules, service_module.__name__, service_module)
    tenant_module = types.ModuleType("bisheng.core.context.tenant")
    tenant_module.get_current_tenant_id = lambda: 1
    monkeypatch.setitem(sys.modules, tenant_module.__name__, tenant_module)
    params = dict(
        file_path=str(path), file_extension="png", file_metadata={"document_id": 12}, tmp_dir=str(tmp_path), **config
    )
    preview = DocFlowLoader(**params)
    pipeline = NormalPipeline(
        loader=preview,
        transformers=[
            SplitterTransformer(
                chunk_size=100, chunk_overlap=0, separator=["\n\n", "\n", ""], separator_rule=["after"] * 3
            )
        ],
    )
    result = pipeline.run(PipelineConfig(stop_at=PipelineStage.TRANSFORMER))
    assert result.documents[0].page_content == "正文"
    assert preview.bbox_list[0].text == "正文"
    fresh_loader = DocFlowLoader(**params)
    assert fresh_loader.load()[0].page_content == "正文"
    assert client.submit.call_count == 1


def stores():
    vector = Mock()
    vector.collection_name = "collection"
    vector._docflow_identity = {"knowledge_id": 1, "model": "embedding-1"}
    vector.embedding_func = Mock()
    vector.embedding_func.embed_documents.side_effect = lambda texts: [[0.1, 0.2] for _ in texts]

    def add_documents(documents):
        return vector.embedding_func.embed_documents([doc.page_content for doc in documents])

    vector.add_documents.side_effect = add_documents
    es = Mock(spec=["_store", "client", "add_documents"])
    es._store = SimpleNamespace(index="index")
    es.client.indices.exists.return_value = True
    es.client.delete_by_query.return_value = {"failures": [], "timed_out": False}
    es.add_documents.return_value = ["es-1"]
    return vector, es


def test_elasticsearch_v1_index_used_for_cleanup():
    state = State()
    vector, es = stores()
    assert not hasattr(es, "index_name")
    Ingest(state).run([Document(page_content="body", metadata={"document_id": 12})], [vector, es])
    es.client.indices.exists.assert_called_once_with(index="index")
    assert es.client.delete_by_query.call_args.kwargs["index"] == "index"


def test_missing_elasticsearch_index_fails_before_vector_cleanup():
    state = State()
    vector, es = stores()
    es._store.index = None
    with pytest.raises(DocFlowError, match="target index is missing"):
        Ingest(state).run([Document(page_content="body", metadata={"document_id": 12})], [vector, es])
    vector.col.delete.assert_not_called()
    es.client.delete_by_query.assert_not_called()


def test_es_failure_resumes_without_reembedding():
    state = State()
    vector, es = stores()
    original = vector.embedding_func
    docs = [Document(page_content="正文", metadata={"document_id": 12})]
    es.add_documents.side_effect = [RuntimeError("ES unavailable"), ["es-1"]]
    with pytest.raises(RuntimeError):
        Ingest(state).run(docs, [vector, es])
    Ingest(state).run(docs, [vector, es])
    Ingest(state).run(docs, [vector, es])
    assert vector.add_documents.call_count == 1
    assert original.embed_documents.call_count == 1
    assert es.add_documents.call_count == 2


def test_status_timestamp_change_does_not_force_reembedding():
    state = State()
    vector, es = stores()
    original = vector.embedding_func
    es.add_documents.side_effect = [RuntimeError("ES unavailable"), ["es-1"]]
    docs = [Document(page_content="正文", metadata={"document_id": 12, "update_time": 100})]
    with pytest.raises(RuntimeError):
        Ingest(state).run(docs, [vector, es])
    docs[0].metadata["update_time"] = 101
    Ingest(state).run(docs, [vector, es])
    assert original.embed_documents.call_count == 1
    assert vector.add_documents.call_count == 1


def test_generated_summary_change_resumes_original_chunk_snapshot():
    state = State()
    vector, es = stores()
    es.add_documents.side_effect = [RuntimeError("ES unavailable"), ["es-1"]]
    original = Document(
        page_content="{<file_title>title</file_title>\n<file_abstract>old</file_abstract>\nbody}",
        metadata={"document_id": 12, "abstract": "old"},
    )
    with pytest.raises(RuntimeError):
        Ingest(state).run([original], [vector, es])
    regenerated = Document(
        page_content=original.page_content.replace("old", "new"), metadata={"document_id": 12, "abstract": "new"}
    )
    Ingest(state).run([regenerated], [vector, es])
    assert vector.add_documents.call_count == 1
    assert es.add_documents.call_args.args[0][0].metadata["abstract"] == "old"


def test_es_cleanup_partial_failure_stops_before_vector_write():
    state = State()
    vector, es = stores()
    es.client.delete_by_query.return_value = {"failures": [{"reason": "rejected"}]}
    with pytest.raises(DocFlowError, match="cleanup incomplete"):
        Ingest(state).run([Document(page_content="body", metadata={"document_id": 12})], [vector, es])
    vector.add_documents.assert_not_called()


def test_uncertain_vector_write_cleans_then_reuses_embedding_cache():
    state = State()
    vector, es = stores()
    original = vector.embedding_func
    docs = [Document(page_content="正文", metadata={"document_id": 12})]
    actual = vector.add_documents.side_effect

    def partial(documents):
        actual(documents)
        raise RuntimeError("write interrupted")

    vector.add_documents.side_effect = partial
    with pytest.raises(RuntimeError):
        Ingest(state).run(docs, [vector, es])
    vector.add_documents.side_effect = actual
    Ingest(state).run(docs, [vector, es])
    assert original.embed_documents.call_count == 1
    assert vector.col.delete.call_count == 2
