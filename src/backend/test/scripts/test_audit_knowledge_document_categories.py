"""分类来源审计只报告可验证差异, 不选择含糊的权威入口。"""

import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from scripts import audit_knowledge_document_categories as subject


def sample():
    def file(fid, kind):
        return {
            "file_id": fid,
            "tenant_id": 1,
            "space_id": 10,
            "knowledge_identity": "document:91",
            "entry_type": kind,
            "active": True,
            "file_category_code": "POL",
            "version_document_ids": [],
        }

    first, second = file(1, "manager"), file(2, "share")
    rows = [
        {
            "file_id": fid,
            "tenant_id": 1,
            "space_id": 10,
            "knowledge_identity": "document:91",
            "file_category_code": "POL",
            "file_category_name": "政策",
        }
        for fid in (1, 2)
    ]
    sources = {
        "files": {1: first, 2: second},
        "documents": {
            91: {
                "tenant_id": 1,
                "lifecycle_status": "active",
                "primary_version_file_id": 1,
            }
        },
        "entries": {91: [first, second]},
    }
    return rows, sources


@pytest.mark.parametrize(
    "issue",
    [
        "es_projection_drift",
        "database_category_conflict",
        "identity_mismatch",
        "missing_or_ambiguous_manager",
        "empty_and_nonempty_category",
    ],
)
def test_audit_distinguishes_sources_and_previews_only_safe_refreshes(issue):
    rows, sources = sample()
    rows[1].update(file_category_code="STD", file_category_name="标准")
    if issue == "database_category_conflict":
        sources["files"][2]["file_category_code"] = "STD"
    elif issue == "identity_mismatch":
        sources["files"][2]["knowledge_identity"] = "document:92"
    elif issue == "missing_or_ambiguous_manager":
        sources["files"][1]["entry_type"] = "share"
    elif issue == "empty_and_nonempty_category":
        rows[1].update(file_category_code=None, file_category_name=None)
    before = deepcopy((rows, sources))
    result = subject.build_report(rows, sources, {"POL": "政策", "STD": "标准"}, 1)
    item = result["problems"][0]
    assert issue in item["issues"]
    assert item["proposed_refresh_file_ids"] == (
        [2] if issue in {"es_projection_drift", "empty_and_nonempty_category"} else []
    )
    assert result["read_only"] is True
    assert (rows, sources) == before


@pytest.mark.parametrize("source", ["es", "database"])
def test_cross_tenant_rows_are_rejected(source):
    rows, sources = sample()
    if source == "es":
        rows[0]["tenant_id"] = 2
    else:
        sources["files"][1]["tenant_id"] = 2
    with pytest.raises(ValueError, match="租户"):
        subject.build_report(rows, sources, {}, 1)


def test_version_identity_mismatch_and_multiple_managers_never_propose_refresh():
    rows, sources = sample()
    sources["files"][1]["version_document_ids"] = [92]
    report = subject.build_report(rows, sources, {"POL": "政策"}, 1)
    assert "identity_mismatch" in report["problems"][0]["issues"]
    assert report["problems"][0]["proposed_refresh_file_ids"] == []
    sources["files"][1]["version_document_ids"] = []
    sources["files"][2]["entry_type"] = "manager"
    report = subject.build_report(rows, sources, {"POL": "政策"}, 1)
    assert "missing_or_ambiguous_manager" in report["problems"][0]["issues"]
    assert report["problems"][0]["expected_category_code"] is None


def test_inconsistent_batch_source_snapshots_require_another_audit():
    rows, sources = sample()
    sources["entries"] = deepcopy(sources["entries"])
    for row in sources["entries"][91]:
        row["file_category_code"] = "STD"
    result = subject.build_report(rows, sources, {"POL": "政策", "STD": "标准"}, 1)
    assert "source_changed_during_audit" in result["problems"][0]["issues"]
    assert result["problems"][0]["proposed_refresh_file_ids"] == []


async def test_runner_batches_sources_and_restores_tenant_on_failure(monkeypatch):
    from bisheng.core.context.tenant import get_current_tenant_id
    from bisheng.core.search.elasticsearch import manager
    from bisheng.knowledge.domain.services.file_classification_label_service import FileClassificationLabelService
    from bisheng.telemetry.domain.repositories.implementations.knowledge_statistics_repository_impl import (
        KnowledgeStatisticsRepositoryImpl,
    )

    rows, sources = sample()
    original = get_current_tenant_id()
    monkeypatch.setattr(manager, "get_es_connection", AsyncMock(return_value=object()))
    monkeypatch.setattr(subject, "read_projection_rows", AsyncMock(return_value=(rows, False)))
    calls = []

    def lookup(files, documents):
        calls.append((files, documents, get_current_tenant_id()))
        return sources

    monkeypatch.setattr(KnowledgeStatisticsRepositoryImpl, "category_audit_sources", lookup)
    monkeypatch.setattr(FileClassificationLabelService, "get_label_lookup_for_tenant", lambda _: ({"POL": "政策"}, {}))
    report = await subject.run_audit(subject.parse_args(["--tenant-id", "1", "--space-id", "10", "--batch-size", "1"]))
    assert report["problem_documents"] == 0
    assert calls == [([1], [91], 1), ([2], [91], 1)]
    assert get_current_tenant_id() == original
    monkeypatch.setattr(subject, "read_projection_rows", AsyncMock(side_effect=RuntimeError("search unavailable")))
    with pytest.raises(RuntimeError):
        await subject.run_audit(subject.parse_args(["--tenant-id", "1", "--space-id", "10"]))
    assert get_current_tenant_id() == original


@pytest.mark.parametrize(
    "options",
    [
        [],
        ["--tenant-id", "1"],
        ["--tenant-id", "0", "--space-id", "1"],
        ["--tenant-id", "1", "--space-id", "1", "--apply"],
        ["--tenant-id", "1", "--space-id", "1", "--limit", "10001"],
    ],
)
def test_cli_requires_bounded_scope_and_has_no_write_mode(options):
    with pytest.raises(SystemExit):
        subject.parse_args(options)


def test_report_file_is_private_and_never_overwritten(monkeypatch, tmp_path):
    output = tmp_path / "audit.json"
    monkeypatch.setattr(subject, "execute", AsyncMock(return_value={"problem_documents": 0, "read_only": True}))
    args = ["--tenant-id", "1", "--space-id", "10", "--output", str(output)]
    assert subject.main(args) == 0
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text())["read_only"] is True
    with pytest.raises(SystemExit):
        subject.main(args)
    assert subject.execute.await_count == 1


def test_audit_failure_does_not_create_a_report(monkeypatch, tmp_path):
    monkeypatch.setattr(subject, "execute", AsyncMock(side_effect=RuntimeError("backend unavailable")))
    output = tmp_path / "audit.json"
    assert subject.main(["--tenant-id", "1", "--space-id", "10", "--output", str(output)]) == 1
    assert not output.exists()


async def test_projection_audit_uses_index_metadata_only_and_marks_limit():
    rows, _ = sample()
    client = type("Client", (), {})()
    client.search = AsyncMock(
        return_value={
            "aggregations": {
                "items": {
                    "buckets": [{"doc_count": 1, "record": {"hits": {"hits": [{"_source": row}]}}} for row in rows]
                }
            }
        }
    )
    found, truncated = await subject.read_projection_rows(client, [{"term": {"tenant_id": 1}}], 1)
    assert len(found) == 1 and truncated
    request = client.search.await_args.kwargs
    assert request["index"] == subject.INDEX and "pit" not in request
    assert request["allow_partial_search_results"] is False
    assert {"term": {"tenant_id": 1}} in request["query"]["bool"]["filter"]
    assert "text" not in request["aggs"]["items"]["aggs"]["record"]["top_hits"]["_source"]
