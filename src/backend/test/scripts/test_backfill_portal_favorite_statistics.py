from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest

from scripts import backfill_portal_favorite_statistics as backfill
from scripts.backfill_portal_favorite_statistics import apply_plan, plan_backfill


def reference(ref_id=103442, file_id=103333, tenant_id=1):
    return {
        "id": ref_id,
        "tenant_id": tenant_id,
        "user_id": 7,
        "create_time": datetime(2026, 7, 30, 10, 30, 46),
        "user_metadata": {"favorite_reference": {"source_file_id": file_id, "source_space_id": 4246}},
    }


class FakeEs:
    def __init__(self):
        self.docs = {
            "103333": {
                "record_type": "file",
                "file_id": 103333,
                "file_type": 1,
                "space_id": 4246,
                "space_name": "个人库",
                "space_level": "personal",
                "space_level_name": "个人库",
                "tenant_id": 1,
                "knowledge_identity": "document:13353",
                "file_name": "停炉完成表.xlsx",
                "uploader_user_id": 7,
                "uploader_user_name": "用户",
            }
        }
        self.writes = []
        self.fail_search = False
        self.fail_bulk = False

    def mget(self, *, index, ids):
        return {"docs": [{"_id": key, "found": key in self.docs, "_source": self.docs.get(key)} for key in ids]}

    def search(self, *, index, body):
        if self.fail_search:
            raise RuntimeError("ES read failed")
        filters = body["query"]["bool"]["filter"]
        expected = {key: value for f in filters for key, value in f["term"].items()}
        matches = [
            source for source in self.docs.values() if all(str(source.get(k)) == str(v) for k, v in expected.items())
        ]
        return {"hits": {"total": {"value": len(matches), "relation": "eq"}, "hits": []}}

    def bulk(self, *, operations, refresh):
        items = []
        for i in range(0, len(operations), 2):
            meta, doc = operations[i]["create"], operations[i + 1]
            key = meta["_id"]
            self.writes.append(key)
            status = 500 if self.fail_bulk else (409 if key in self.docs else 201)
            if status == 201:
                self.docs[key] = deepcopy(doc)
            items.append({"create": {"_id": key, "status": status}})
        return {"items": items}


def plan(es, refs):
    return plan_backfill(refs, es, tenant_id=1, created_before=datetime(2026, 9, 1))


def test_preview_and_repeat_apply_count_one_real_creation_once():
    es = FakeEs()
    report = plan(es, [reference()])
    assert es.writes == []
    assert len(report["candidates"]) == 1
    entry = report["candidates"][0]
    assert entry["document"]["local_date"] == "2026-07-30"
    assert entry["document"]["favorite_count"] == 1
    assert apply_plan(es, report["candidates"]) == {"created": 1, "already_exists": 0, "verified": 1}
    assert apply_plan(es, report["candidates"]) == {"created": 0, "already_exists": 1, "verified": 1}
    assert plan(es, [reference()])["candidates"] == []


def test_existing_daily_count_and_unprovable_origins_are_not_added():
    es = FakeEs()
    es.docs["daily-1"] = {
        "record_type": "favorite_daily",
        "file_id": 103333,
        "local_date": "2026-07-30",
        "favorite_count": 1,
    }
    refs = [reference(), reference(2, file_id=999), reference(3, tenant_id=2)]
    report = plan(es, refs)
    assert report["candidates"] == []
    assert {row["reason"] for row in report["skipped"]} == {
        "existing_daily_statistics",
        "source_snapshot_missing",
        "other_tenant",
    }
    assert es.writes == []


def test_read_and_write_failures_propagate_instead_of_becoming_missing_records():
    es = FakeEs()
    es.fail_search = True
    with pytest.raises(RuntimeError, match="ES read failed"):
        plan(es, [reference()])
    es.fail_search = False
    report = plan(es, [reference()])
    es.fail_bulk = True
    with pytest.raises(RuntimeError, match="write failed"):
        apply_plan(es, report["candidates"])


def test_conflicting_identity_is_not_overwritten():
    es = FakeEs()
    report = plan(es, [reference()])
    entry = report["candidates"][0]
    es.docs[entry["id"]] = {**entry["document"], "favorite_count": 99}
    with pytest.raises(RuntimeError, match="identity conflict"):
        apply_plan(es, report["candidates"])
    assert es.docs[entry["id"]]["favorite_count"] == 99


def test_cli_default_preview_never_writes(monkeypatch, tmp_path):
    from bisheng.core.search.elasticsearch import manager

    es = FakeEs()
    es.indices = SimpleNamespace(exists=lambda **_: True)
    es.close = lambda: None
    monkeypatch.setattr(manager, "get_statistics_es_connection_sync", lambda: es)
    monkeypatch.setattr(backfill, "load_references", lambda *_: [reference()])
    report_path = tmp_path / "preview.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "backfill",
            "--tenant-id",
            "1",
            "--created-before",
            "2026-09-01",
            "--reference-id",
            "103442",
            "--report",
            str(report_path),
        ],
    )
    assert backfill.main() == 0
    assert '"mode": "dry-run"' in report_path.read_text()
    assert es.writes == []


@pytest.mark.parametrize("field,value", [("tenant_id", 2), ("space_level", "unknown"), ("knowledge_identity", None)])
def test_source_snapshot_must_have_same_tenant_and_valid_identity(field, value):
    es = FakeEs()
    es.docs["103333"][field] = value
    report = plan(es, [reference()])
    assert report["candidates"] == []
    assert report["skipped"][0]["reason"] == "source_snapshot_invalid_or_changed"
