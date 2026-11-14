"""Pure web material planning against the actual existing Utils source oracle."""

import builtins
import importlib
import socket
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from test.knowledge_unification.test_file_worker import source_module


def api():
    return importlib.import_module("bisheng.knowledge.application.web_link_upload")


@pytest.fixture
def actual_utils(monkeypatch):
    import bisheng.common.services.base as base

    backend = Path(__file__).resolve().parents[2]
    actual_base = source_module("_web_material_actual_base", backend / "bisheng/common/services/base.py")
    monkeypatch.setattr(base, "BaseService", actual_base.BaseService)
    return source_module(
        "_web_material_actual_utils", backend / "bisheng/knowledge/domain/services/knowledge_utils.py"
    ).KnowledgeUtils


def prepare(**changes):
    return api().PreparedWebLink(
        **(
            {
                "file_name": "原始网页.html",
                "content_hash": "original-hash-without-recomputation",
                "markdown_bytes": "# 原样正文\r\n".encode(),
                "html_snapshot_bytes": "<html>原始快照</html>".encode(),
                "split_rule": '  {"force_ocr":0,"separator":["\\\\n",""],"other":false}  ',
                "user_metadata": {
                    "source_url": "https://private.invalid/source",
                    "final_url": "https://private.invalid/final",
                    "html_snapshot_object_name": "untrusted/old-key",
                    "typed": [None, False, 0, 0.0, {"value": "文本"}],
                },
            }
            | changes
        )
    )


@pytest.mark.parametrize("ident", [1, 37, 9007199254740993])
@pytest.mark.parametrize("html", [b"", b"<html>original\x00\xff</html>"])
async def test_original_utils_md_key_html_metadata_and_put_bytes_are_exact(actual_utils, monkeypatch, ident, html):
    module = api()
    expected = actual_utils.get_knowledge_file_object_name(ident, "web_link.md")
    actual_method, calls = actual_utils.get_knowledge_file_object_name, []

    def invoke(cls, file_id, file_name):
        calls.append((file_id, file_name))
        return actual_method(file_id, file_name)

    monkeypatch.setattr(actual_utils, "get_knowledge_file_object_name", classmethod(invoke))
    monkeypatch.setattr(module, "KnowledgeUtils", actual_utils)
    prepared = prepare(html_snapshot_bytes=html)
    result = module.build_web_link_objects(prepared, file_id=ident)
    assert calls == [(ident, "web_link.md")]
    assert result.objects[0].name == expected == f"original/{ident}.md"
    assert result.objects[0].content_type == "text/markdown; charset=utf-8"
    assert result.objects[0].content is prepared.markdown_bytes
    assert result.user_metadata["html_snapshot_object_name"] == f"preview/{ident}.html"
    assert len(result.objects) == (2 if html else 1)
    if html:
        assert result.objects[1].name == f"preview/{ident}.html"
        assert result.objects[1].content_type == "text/html; charset=utf-8" and result.objects[1].content is html
    assert (
        prepared.file_name == "原始网页.html"
        and prepared.user_metadata["html_snapshot_object_name"] == "untrusted/old-key"
    )


@pytest.mark.parametrize("name", ["Unicode 空格.html", "report.HTML", "no_extension"])
def test_display_name_hash_resolved_rule_and_unparsed_bytes_never_change(actual_utils, monkeypatch, name):
    module = api()
    monkeypatch.setattr(module, "KnowledgeUtils", actual_utils)
    prepared = prepare(
        file_name=name, markdown_bytes=b"\xff\x00\xef\xbb\xbf", split_rule="opaque original resolved rule"
    )
    result = module.build_web_link_objects(prepared, file_id=17)
    assert result.objects[0].name == actual_utils.get_knowledge_file_object_name(17, "web_link.md")
    assert result.objects[0].content == b"\xff\x00\xef\xbb\xbf"
    assert prepared.file_name == name and prepared.split_rule == "opaque original resolved rule"
    assert prepared.content_hash == "original-hash-without-recomputation"


@pytest.mark.parametrize("ident", [True, False, 0, -1, 1.5, "7", None])
def test_invalid_internal_file_id_is_not_coerced_or_passed_to_utils(monkeypatch, ident):
    module = api()

    def forbidden(*args, **kwargs):
        pytest.fail("invalid ID reached Utils")

    monkeypatch.setattr(module.KnowledgeUtils, "get_knowledge_file_object_name", forbidden)
    with pytest.raises(ValueError):
        module.build_web_link_objects(prepare(), file_id=ident)


def test_input_prepared_and_each_plan_metadata_are_deeply_isolated(actual_utils, monkeypatch):
    module = api()
    monkeypatch.setattr(module, "KnowledgeUtils", actual_utils)
    supplied = {"source_url": "private-original", "typed": [False, 0, 0.0, {"nested": ["original"]}]}
    prepared = prepare(user_metadata=supplied)
    supplied["typed"][3]["nested"].append("caller changed")
    assert prepared.user_metadata["typed"][3]["nested"] == ["original"]
    first = module.build_web_link_objects(prepared, file_id=17)
    second = module.build_web_link_objects(prepared, file_id=18)
    first.user_metadata["typed"][3]["nested"].append("plan changed")
    assert second.user_metadata["typed"][3]["nested"] == prepared.user_metadata["typed"][3]["nested"] == ["original"]
    assert first.user_metadata["html_snapshot_object_name"] == "preview/17.html"
    assert second.user_metadata["html_snapshot_object_name"] == "preview/18.html"
    assert [type(value) for value in second.user_metadata["typed"][:3]] == [bool, int, float]


def test_material_and_object_plan_are_frozen_slots_and_payloads_are_not_in_repr(actual_utils, monkeypatch):
    module = api()
    monkeypatch.setattr(module, "KnowledgeUtils", actual_utils)
    prepared = prepare(
        markdown_bytes=b"private-markdown",
        html_snapshot_bytes=b"private-html",
        split_rule="private-rules",
        user_metadata={"credential": "private-value"},
    )
    result = module.build_web_link_objects(prepared, file_id=17)
    for value in (prepared, result, *result.objects):
        assert not hasattr(value, "__dict__")
        assert not any(
            secret in repr(value) for secret in ("private-markdown", "private-html", "private-rules", "private-value")
        )
    with pytest.raises(FrozenInstanceError):
        prepared.file_name = "changed"
    with pytest.raises(FrozenInstanceError):
        result.objects = ()
    with pytest.raises(FrozenInstanceError):
        result.objects[0].name = "arbitrary/key"


def test_planning_has_zero_file_network_storage_database_or_permission_io(actual_utils, monkeypatch):
    module = api()
    monkeypatch.setattr(module, "KnowledgeUtils", actual_utils)
    prepared = prepare()
    import bisheng.core.database as database
    import bisheng.core.storage.minio.minio_manager as storage
    import bisheng.permission.application.access as access

    def forbidden(*args, **kwargs):
        pytest.fail("pure web material planning performed external IO")

    with monkeypatch.context() as guard:
        guard.setattr(builtins, "open", forbidden)
        guard.setattr(socket, "socket", forbidden)
        guard.setattr(database, "get_async_db_session", forbidden)
        guard.setattr(database, "get_sync_db_session", forbidden)
        guard.setattr(storage, "get_minio_storage_sync", forbidden)
        guard.setattr(access, "get_f048_resource_adapter", forbidden)
        result = module.build_web_link_objects(prepared, file_id=17)
    assert len(result.objects) == 2
