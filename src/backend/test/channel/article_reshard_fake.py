"""Observable in-memory ES API double; exercises the production migration orchestration."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

from scripts.article_reshard_plan import MigrationError


class FakeEs:
    def __init__(self, *, alias=False, fault=None):
        self.source = "articles-old" if alias else "channel_articles"
        self.indexes = {
            self.source: {
                "settings": {
                    "index": {
                        "uuid": "sourceUUID",
                        "number_of_shards": "1",
                        "number_of_replicas": "0",
                        "refresh_interval": "-1",
                    }
                },
                "mappings": {"properties": {"title": {"type": "keyword"}}},
                "aliases": {"channel_articles": {}} if alias else {},
            }
        }
        self.docs = {self.source: {"old": {"_id": "old", "_routing": "u", "_source": {"title": "before"}}}}
        self.pending = {
            self.source: [
                ("new", {"_id": "new", "_source": {"title": "new"}}),
                ("old", {"_id": "old", "_routing": "u", "_source": {"title": "after"}}),
            ]
        }
        self.writes = []
        self.fault = fault
        self.indices = self
        self.cluster = SimpleNamespace(
            health=AsyncMock(return_value={"status": "green", "active_shards": 1}),
            get_settings=AsyncMock(return_value={"defaults": {}}),
        )
        self.nodes = SimpleNamespace(
            stats=AsyncMock(
                return_value={
                    "nodes": {
                        "n": {
                            "roles": ["data"],
                            "fs": {"total": {"total_in_bytes": 1000000, "available_in_bytes": 900000}},
                        }
                    }
                }
            )
        )
        self.tasks = SimpleNamespace(
            list=AsyncMock(return_value={"nodes": {}}), get=AsyncMock(side_effect=self.task_get)
        )
        self.jobs = {}
        self.cursor = {}

    def resolve(self, index):
        return [index] if index in self.indexes else [n for n, v in self.indexes.items() if index in v["aliases"]]

    async def get(self, *, index):
        return {n: deepcopy(self.indexes[n]) for n in self.resolve(index)}

    async def exists(self, *, index):
        return bool(self.resolve(index))

    async def count(self, *, index):
        return {"count": sum(len(self.docs[n]) for n in self.resolve(index)), "_shards": {"failed": 0}}

    async def stats(self, **kwargs):
        return {"_all": {"total": {"store": {"size_in_bytes": 100}}}, "_shards": {"failed": 0}}

    async def simulate_index_template(self, **kwargs):
        return {"template": {"aliases": {"bad": {}} if self.fault == "template_alias" else {}}}

    async def get_template(self, **kwargs):
        return {}

    async def create(self, *, index, settings, mappings, **kwargs):
        if index in self.indexes:
            raise MigrationError("index already exists")
        self.writes.append(("create", index))
        value = deepcopy(settings)
        value["uuid"] = "uuid-" + index
        self.indexes[index] = {"settings": {"index": value}, "mappings": deepcopy(mappings), "aliases": {}}
        self.docs[index] = {}
        return {"acknowledged": True, "shards_acknowledged": True}

    async def add_block(self, *, index, **kwargs):
        self.writes.append(("block", index))
        self.indexes[index]["settings"]["index"].setdefault("blocks", {})["write"] = True
        return {"acknowledged": True, "shards_acknowledged": True, "indices": [{"name": index, "blocked": True}]}

    async def refresh(self, *, index):
        self.writes.append(("refresh", index))
        for key, value in self.pending.pop(index, []):
            if value is None:
                self.docs[index].pop(key, None)
            else:
                self.docs[index][key] = value
        return {"_shards": {"failed": 0}}

    async def put_mapping(self, *, index, body):
        self.writes.append(("metadata", index))
        self.indexes[index]["mappings"]["_meta"] = deepcopy(body["_meta"])
        return {"acknowledged": True}

    async def put_settings(self, *, index, body):
        self.writes.append(("settings", index))
        self.indexes[index]["settings"]["index"].update(deepcopy(body["index"]))
        return {"acknowledged": True}

    async def search(self, *, index, **kwargs):
        cursor = "scroll-" + index
        hits = list(deepcopy(self.docs[index]).values())
        size = kwargs["size"]
        self.cursor[cursor] = {"hits": hits[size:], "size": size}
        return {
            "_scroll_id": cursor,
            "_shards": {"failed": 0},
            "hits": {"hits": hits[:size]},
        }

    async def scroll(self, *, scroll_id, **kwargs):
        state = self.cursor[scroll_id]
        page = state["hits"][: state["size"]]
        state["hits"] = state["hits"][state["size"] :]
        return {"_scroll_id": scroll_id, "_shards": {"failed": 0}, "hits": {"hits": page}}

    async def clear_scroll(self, **kwargs):
        return {"succeeded": True}

    async def reindex(self, *, body, **kwargs):
        source, target = body["source"]["index"], body["dest"]["index"]
        self.writes.append(("copy", target))
        self.docs[target] = deepcopy(self.docs[source])
        if self.fault == "corrupt" and "reshard" in target:
            self.docs[target]["old"]["_source"]["title"] = "corrupt"
        task = "task-" + str(len(self.jobs))
        response = {
            "total": len(self.docs[source]),
            "created": len(self.docs[source]),
            "updated": 0,
            "version_conflicts": 0,
            "failures": [],
            "timed_out": False,
        }
        if self.fault == "task_failed":
            response["failures"] = [{"cause": "failed"}]
        self.jobs[task] = {"completed": True, "response": response}
        return {"task": task}

    async def task_get(self, *, task_id, **kwargs):
        return self.jobs[task_id]

    async def update_aliases(self, *, actions):
        self.writes.append(("cutover", actions))
        for action in actions:
            if "remove_index" in action:
                self.indexes.pop(action["remove_index"]["index"])
            elif "remove" in action:
                value = action["remove"]
                self.indexes[value["index"]]["aliases"].pop(value["alias"], None)
            elif "add" in action:
                value = deepcopy(action["add"])
                index, alias = value.pop("index"), value.pop("alias")
                self.indexes[index]["aliases"][alias] = value
        if self.fault == "cutover_unknown":
            raise TimeoutError("response lost after cutover")
        return {"acknowledged": True, "errors": False}
