import json
import sys
from copy import deepcopy
from io import StringIO

import pytest

from scripts import backfill_dashboard_original_organizations as script


def hit():
    return {
        "_id": "11",
        "_seq_no": 2,
        "_primary_term": 1,
        "_source": {
            "record_type": "file",
            "tenant_id": 1,
            "file_id": 11,
            "space_id": 20,
            "knowledge_identity": "document:3",
            "preview_count": 9,
        },
    }


def desired():
    return {
        **hit()["_source"],
        "original_space_name": "原始库",
        "original_upload_department_name": "原始部门",
        "_origin_id": 10,
        "_fallback": False,
    }


class Es:
    def __init__(self):
        self.row = hit()
        self.calls = []
        self.conflict = False

    def get(self, **_kwargs):
        return deepcopy(self.row)

    def update(self, **kwargs):
        self.calls.append(kwargs)
        if self.conflict:
            raise RuntimeError("version conflict")
        assert kwargs["if_seq_no"] == self.row["_seq_no"]
        assert kwargs["if_primary_term"] == self.row["_primary_term"]
        if "doc" in kwargs:
            self.row["_source"].update(kwargs["doc"])
        else:
            for key, value in kwargs["script"]["params"]["before"].items():
                if value["present"]:
                    self.row["_source"][key] = value["value"]
                else:
                    self.row["_source"].pop(key, None)
        self.row["_seq_no"] += 1
        return {"result": "updated"}


def test_preview_apply_repeat_and_field_level_rollback(tmp_path):
    es = Es()
    candidate, reason = script.candidate(es.row, desired(), 1, [])
    assert reason == "candidate" and es.calls == []
    journal = tmp_path / "journal.jsonl"
    with script.secure_open(journal) as stream:
        script.apply_one(es, "stats", candidate, desired(), 1, [], stream)
    assert journal.stat().st_mode & 0o777 == 0o600
    assert es.row["_source"]["original_space_name"] == "原始库"
    assert es.row["_source"]["preview_count"] == 9
    assert set(es.calls[0]["doc"]) == {"original_space_name", "original_upload_department_name"}
    assert script.candidate(es.row, desired(), 1, [])[1] == "unchanged"
    entry = script.load_journal(journal)[0]
    es.row["_source"]["preview_count"] = 12
    script.rollback_one(es, "stats", entry, 1, StringIO(), apply=True)
    assert "original_space_name" not in es.row["_source"]
    assert es.row["_source"]["preview_count"] == 12


@pytest.mark.parametrize("change", ["existing", "tenant", "identity", "daily", "source", "origin"])
def test_unprovable_or_conflicting_records_never_write(change):
    row, source = hit(), desired()
    if change == "existing":
        row["_source"]["original_space_name"] = "已有不同来源"
    elif change == "tenant":
        source["tenant_id"] = 2
    elif change == "identity":
        source["knowledge_identity"] = "document:4"
    elif change == "daily":
        row["_source"]["record_type"] = "preview_daily"
    elif change == "origin":
        source.pop("original_space_name")
    else:
        source = None
    assert script.candidate(row, source, 1, [])[0] is None


def test_drift_concurrency_and_rollback_conflict_fail_closed(tmp_path):
    es = Es()
    planned, _ = script.candidate(es.row, desired(), 1, [])
    with pytest.raises(RuntimeError, match="drift"):
        script.apply_one(es, "stats", planned, {**desired(), "_origin_id": 12}, 1, [], StringIO())
    assert es.calls == []
    es.conflict = True
    journal = tmp_path / "journal.jsonl"
    with script.secure_open(journal) as stream, pytest.raises(RuntimeError, match="version conflict"):
        script.apply_one(es, "stats", planned, desired(), 1, [], stream)
    assert len(script.load_journal(journal)) == 1
    es.conflict = False
    es.row["_source"]["original_space_name"] = "并发更新的值"
    with pytest.raises(RuntimeError, match="rollback drift"):
        script.rollback_one(es, "stats", script.load_journal(journal)[0], 1, StringIO(), apply=True)
    assert es.row["_source"]["original_space_name"] == "并发更新的值"


def test_scope_source_absence_and_existing_output(tmp_path):
    row = hit()
    assert script.candidate(row, desired(), 1, [99])[1] == "scope_mismatch"
    empty = {key: value for key, value in desired().items() if key not in script.FIELDS}
    assert script.candidate(row, empty, 1, [])[1] == "unresolved"
    row["_source"]["original_space_name"] = "  "
    result, _ = script.candidate(row, desired(), 1, [])
    assert result["before"]["original_space_name"] == {"present": True, "value": "  "}
    output = tmp_path / "output"
    output.write_text("保留")
    with pytest.raises(FileExistsError):
        script.secure_open(output)
    assert output.read_text() == "保留"


@pytest.mark.parametrize("fault", [{"timed_out": True}, {"terminated_early": True}, {"_shards": {"failed": 1}}])
def test_partial_scan_fails_without_writing(fault):
    class ScanEs:
        def search(self, **kwargs):
            self.query = kwargs["query"]
            return {"_scroll_id": "cursor", "hits": {"hits": [hit()]}, **fault}

        def clear_scroll(self, **kwargs):
            self.cleared = kwargs["scroll_id"]

    es = ScanEs()
    with pytest.raises(RuntimeError, match="incomplete"):
        list(script.scan(es, "stats", 1, [20], 200))
    assert es.cleared == "cursor"
    assert es.query["bool"]["filter"] == [
        {"term": {"record_type": "file"}},
        {"term": {"tenant_id": 1}},
        {"terms": {"space_id": [20]}},
    ]


def test_rollback_rejects_non_original_fields():
    entry, _ = script.candidate(hit(), desired(), 1, [])
    entry["patch"]["preview_count"] = 0
    es = Es()
    with pytest.raises(RuntimeError, match="invalid candidate"):
        script.rollback_one(es, "stats", entry, 1, StringIO(), apply=True)
    assert es.calls == []


def test_cli_preview_plan_apply_and_rollback(monkeypatch, tmp_path):
    from bisheng.core.search.elasticsearch import manager

    es = Es()
    monkeypatch.setattr(manager, "get_es_connection_sync", lambda: es)
    monkeypatch.setattr(script, "binding", lambda *_: {"index": "stats", "uuid": "same-index"})
    monkeypatch.setattr(script, "scan", lambda *_: iter([[es.row]]))
    monkeypatch.setattr(script, "sources", lambda *_: {11: desired()})
    plan, write, rollback = [tmp_path / name for name in ("plan.json", "write.jsonl", "rollback.jsonl")]
    monkeypatch.setattr(sys, "argv", ["backfill", "--tenant-id", "1", "--output", str(plan)])
    assert script.main() == 0
    assert es.calls == []
    assert json.loads(plan.read_text())["counts"]["scanned"] == 1
    monkeypatch.setattr(sys, "argv", ["backfill", "--plan", str(plan), "--apply", "--output", str(write)])
    assert script.main() == 0
    assert json.loads(write.read_text().splitlines()[-1])["counts"] == {"updated_verified": 1}
    monkeypatch.setattr(sys, "argv", ["backfill", "--rollback", str(write), "--apply", "--output", str(rollback)])
    assert script.main() == 0
    assert "original_space_name" not in es.row["_source"]
