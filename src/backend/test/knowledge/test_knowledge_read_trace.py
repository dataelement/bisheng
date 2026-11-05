"""Diagnostic logs identify stalled reads without logging content or changing outcomes."""

from types import SimpleNamespace

import pytest

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.core.logger import trace_id_var


def test_read_trace_records_phase_and_failure_without_exception_content(monkeypatch):
    from bisheng.knowledge.domain import read_diagnostics as module

    lines = []
    monkeypatch.setattr(module, "emit_metric", lambda domain, **fields: lines.append((domain, fields)))
    tenant = set_current_tenant_id(42)
    trace = trace_id_var.set("read-trace-1")
    now = [10.0]
    try:
        with pytest.raises(RuntimeError, match="private query"):
            with module.KnowledgeReadTrace(
                "children", clock=lambda: now[0], space_id=142, parent_id=2874, source="file_list"
            ) as event:
                event.stage("authorize")
                now[0] = 10.25
                event.stage("scan_visible")
                now[0] = 10.75
                raise RuntimeError("private query and credentials must not be logged")
    finally:
        trace_id_var.reset(trace)
        current_tenant_id.reset(tenant)
    assert [fields["event"] for _, fields in lines] == ["start", "stage_start", "stage_start", "end"]
    final = lines[-1][1]
    assert final["trace_id"] == "read-trace-1"
    assert final["tenant_id"] == 42
    assert final["parent_id"] == 2874
    assert final["status"] == "error"
    assert final["stage"] == "scan_visible"
    assert final["authorize_elapsed_ms"] == 250
    assert final["scan_visible_elapsed_ms"] == 500
    assert final["total_elapsed_ms"] == 750
    assert final["error_type"] == "RuntimeError"
    assert "private query" not in repr(lines)


def test_success_trace_records_counts_and_preserves_business_result(monkeypatch):
    from bisheng.knowledge.domain import read_diagnostics as module

    lines = []
    monkeypatch.setattr(module, "emit_metric", lambda domain, **fields: lines.append(fields))
    with module.KnowledgeReadTrace("delete_visibility", clock=lambda: 1.0, space_id=142) as event:
        event.stage("footprints")
        event.update(footprint_count=1000, request_count=1, returned_count=900)
        result = {1, 2, 3}
    assert result == {1, 2, 3}
    assert lines[-1]["status"] == "success"
    assert lines[-1]["footprint_count"] == 1000
    assert lines[-1]["request_count"] == 1
    assert lines[-1]["returned_count"] == 900


@pytest.mark.parametrize(
    "hint,file_type,expected",
    [
        ("folder_tree", 0, "folder_tree"),
        ("file_list", None, "file_list"),
        ("injected\nsecret", 0, "folders_only"),
        (None, None, "children"),
    ],
)
def test_source_hint_is_bounded(hint, file_type, expected):
    from bisheng.knowledge.domain.read_diagnostics import knowledge_list_source

    assert (
        knowledge_list_source(
            SimpleNamespace(headers={"x-knowledge-list-source": hint}), operation="children", file_type=file_type
        )
        == expected
    )


@pytest.mark.parametrize("operation", ["children", "search"])
async def test_real_listing_logs_end_for_empty_page_without_changing_payload(monkeypatch, operation):
    from unittest.mock import AsyncMock

    from bisheng.knowledge.domain import read_diagnostics as diagnostics
    from bisheng.knowledge.domain.services import knowledge_space_service as module

    lines = []
    monkeypatch.setattr(diagnostics, "emit_metric", lambda domain, **fields: lines.append(fields))
    svc = module.KnowledgeSpaceService(
        SimpleNamespace(headers={"x-knowledge-list-source": "search" if operation == "search" else "file_list"}),
        SimpleNamespace(is_global_super=False),
    )
    svc.version_repo = None
    svc._require_container_read_permission = AsyncMock(return_value=(SimpleNamespace(user_id=9), None))
    svc._scan_visible_child_items = AsyncMock(return_value=([], False, None))
    svc._scan_visible_search_items = AsyncMock(return_value=([], False))
    svc._enrich_with_version_info = AsyncMock()
    svc._handle_file_folder_extra_info = AsyncMock(return_value=[])
    svc._get_file_change_excluded_ids = AsyncMock(return_value=set())
    monkeypatch.setattr(
        module,
        "KnowledgeFolderDeletionService",
        lambda space_id: SimpleNamespace(project_page=AsyncMock(return_value=None)),
    )
    if operation == "children":
        result = await svc.list_space_children(142)
        result = result.model_dump()
    else:
        result = await svc.search_space_children(142)
    assert result["data"] == []
    assert result["has_more"] is False
    assert result["scope_deletion_status"] is None
    assert lines[0]["event"] == "start"
    assert lines[-1]["event"] == "end"
    assert lines[-1]["status"] == "success"
    assert lines[-1]["returned_count"] == 0
    assert lines[-1]["stage"] == "deletion_status"
    assert lines[-1]["source"] == ("search" if operation == "search" else "file_list")


async def test_real_listing_authorization_failure_has_current_stage_and_propagates(monkeypatch):
    from unittest.mock import AsyncMock

    from bisheng.knowledge.domain import read_diagnostics as diagnostics
    from bisheng.knowledge.domain.services import knowledge_space_service as module

    lines = []
    monkeypatch.setattr(diagnostics, "emit_metric", lambda domain, **fields: lines.append(fields))
    svc = module.KnowledgeSpaceService(None, SimpleNamespace(is_global_super=False))
    error = LookupError("secret authority detail")
    svc._require_container_read_permission = AsyncMock(side_effect=error)
    with pytest.raises(LookupError) as caught:
        await svc.list_space_children(142, parent_id=2874)
    assert caught.value is error
    assert lines[-1]["status"] == "error"
    assert lines[-1]["stage"] == "authorize"
    assert lines[-1]["error_type"] == "LookupError"
    assert lines[-1]["parent_id"] == 2874
    assert "secret authority detail" not in repr(lines)
