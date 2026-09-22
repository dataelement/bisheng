# ruff: noqa: RUF002
"""迁移失败时不切换，成功时保留全部历史及可核对的源备份。"""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from scripts import migrate_knowledge_document_statistics as module


class Store:
    def __init__(self):
        self.data = {
            module.SOURCE: {
                "1": {"record_type": "file", "file_id": 1},
                "p": {"record_type": "preview_daily", "preview_count": 7},
                "d": {"record_type": "download_daily", "download_count": 4},
                "other": {"record_type": "future_type", "value": "保留未知历史"},
            }
        }
        self.indices = self
        self.aliases = {}
        self.writes = []
        self.meta = {}

    def get(self, *, index):
        index = self.aliases.get(index, index)
        return {
            index: {
                "mappings": {"_meta": self.meta.get(index, {})},
                "settings": {"index": {"number_of_shards": "1"}},
                "aliases": {},
            }
        }

    def exists(self, *, index):
        return index in self.data

    def put_settings(self, **kwargs):
        self.writes.append(("settings", kwargs))

    def refresh(self, **kwargs):
        self.writes.append(("refresh", kwargs))

    def create(self, *, index, **kwargs):
        self.writes.append(("create", kwargs))
        self.data[index] = {}

    def clone(self, *, index, target, **kwargs):
        self.data[target] = deepcopy(self.data[index])
        return {"acknowledged": True}

    def put_mapping(self, *, index, _meta):
        self.meta[index] = _meta

    def update_aliases(self, *, actions):
        for action in actions:
            if "remove_index" in action:
                del self.data[action["remove_index"]["index"]]
            if "add" in action:
                self.aliases[action["add"]["alias"]] = action["add"]["index"]
        return {"acknowledged": True}


def args(apply=False):
    return SimpleNamespace(
        target_index=module.SOURCE + "-v2",
        backup_index=module.SOURCE + "-backup",
        apply=apply,
        writers_paused=True,
        confirm_index=module.SOURCE,
    )


def files():
    yield "1", {"record_type": "file", "file_id": 1, "knowledge_identity": "document:99"}


@pytest.fixture
def store(monkeypatch):
    def scan(client, index):
        yield from ({"_id": key, "_source": deepcopy(value)} for key, value in client.data[index].items())

    def bulk(client, actions, **kwargs):
        for action in actions:
            assert action["_id"] not in client.data[action["_index"]]
            client.data[action["_index"]][action["_id"]] = deepcopy(action["_source"])

    monkeypatch.setattr(module, "scan", scan)
    monkeypatch.setattr("elasticsearch.helpers.bulk", bulk)
    return Store()


def test_dry_run_never_writes(store):
    result = module.migrate(store, args(), files=files)
    assert result["mode"] == "dry-run"
    assert result["source_statistics"]["operation_counts"]["preview_count"] == 7
    assert store.writes == []
    assert store.aliases == {}


def test_success_preserves_history_backup_and_replaces_only_inventory(store):
    original = deepcopy(store.data[module.SOURCE])
    options = args(True)
    result = module.migrate(store, options, files=files)
    assert result["switched"] is True
    assert store.data[options.backup_index] == original
    assert store.aliases[module.SOURCE] == options.target_index
    assert store.data[options.target_index] == {**original, **dict(files())}
    assert store.meta[options.target_index]["document_statistics_version"] == 1


@pytest.mark.parametrize("failure", ["bulk", "inventory_changed", "lease", "corrupt_backup"])
def test_failed_validation_does_not_switch_and_restores_source(store, monkeypatch, failure):
    original = deepcopy(store.data[module.SOURCE])
    options = args(True)

    def renew():
        return failure != "lease"

    calls = 0

    def changing_files():
        nonlocal calls
        calls += 1
        yield from files()
        if failure == "inventory_changed" and calls > 1:
            yield "2", {"record_type": "file", "file_id": 2}

    if failure == "bulk":
        monkeypatch.setattr(
            "elasticsearch.helpers.bulk", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("bulk failed"))
        )
    if failure == "corrupt_backup":
        monkeypatch.setattr(store, "clone", lambda **kw: store.data.update({options.backup_index: {}}))
    with pytest.raises(RuntimeError):
        module.migrate(store, options, files=changing_files, renew=renew)
    assert store.aliases == {}
    assert store.data[module.SOURCE] == original
    assert store.writes[-1] == ("settings", {"index": module.SOURCE, "settings": {"index.blocks.write": "false"}})


def test_existing_targets_are_never_overwritten(store):
    options = args(True)
    store.data[options.backup_index] = {}
    with pytest.raises(ValueError, match="已存在"):
        module.migrate(store, options, files=files)
    assert store.writes == []


def test_rollback_keeps_new_index_and_checks_for_new_data(store):
    options = args(True)
    original = deepcopy(store.data[module.SOURCE])
    module.migrate(store, options, files=files)
    options.apply = False
    before = list(store.writes)
    assert module.rollback(store, options)["mode"] == "rollback-dry-run"
    assert store.writes == before
    store.data[options.target_index]["late"] = {"record_type": "preview_daily", "preview_count": 1}
    options.apply = True
    with pytest.raises(RuntimeError, match="新写入"):
        module.rollback(store, options)
    assert store.aliases[module.SOURCE] == options.target_index
    del store.data[options.target_index]["late"]
    assert module.rollback(store, options)["switched"] is True
    assert store.aliases[module.SOURCE] == options.backup_index
    assert store.data[options.backup_index] == original
    assert options.target_index in store.data


@pytest.mark.parametrize(
    "response",
    [
        {"timed_out": True, "hits": {"total": {"relation": "eq", "value": 0}, "hits": []}},
        {"_shards": {"failed": 1}, "hits": {"total": {"relation": "eq", "value": 0}, "hits": []}},
        {"hits": {"total": {"relation": "eq", "value": 1}, "hits": []}},
    ],
)
def test_snapshot_rejects_empty_partial_or_truncated_results(response):
    closed = []
    client = SimpleNamespace(
        search=lambda **kwargs: {**response, "_scroll_id": "s"}, clear_scroll=lambda **kwargs: closed.append(kwargs)
    )
    with pytest.raises(RuntimeError):
        list(module.scan(client, "index"))
    assert closed == [{"scroll_id": "s"}]
