"""Read-only M2 task facts; broker inventory remains a separate required port."""

from dataclasses import asdict

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.knowledge.application.unification_inventory_codec import record_from_values
from bisheng.knowledge.domain.repositories.unification_task_repository import (
    QueuedFileFact,
    TaskFact,
    UnificationTaskRepository,
    task_digest,
)

PREFIX = "{bisheng_fs}:"
BATCH = 200


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason=f"migration_tasks_{reason}")


def _text(value):
    if type(value) is bytes:
        value = value.decode("utf-8", errors="strict")
    if type(value) is not str or "\x00" in value:
        _blocked("invalid_redis_text")
    return value


def _ident(value):
    text = _text(value)
    if not text or not text.isascii() or not text.isdecimal() or int(text) <= 0:
        _blocked("invalid_redis_identity")
    return text


def _cursor(value):
    if type(value) in (bytes, str):
        value = _text(value)
        if not value or not value.isascii() or not value.isdecimal():
            _blocked("invalid_redis_cursor")
        value = int(value)
    if type(value) is not int or value < 0:
        _blocked("invalid_redis_cursor")
    return value


def _page(value, *, mapping=False):
    if type(value) not in (list, tuple) or len(value) != 2:
        _blocked("invalid_redis_page")
    cursor, values = value
    if (mapping and type(values) is not dict) or (not mapping and type(values) is not list):
        _blocked("invalid_redis_page")
    return cursor, values


def _payload(value):
    if type(value) is not dict:
        _blocked("invalid_payload")
    result = {_text(key): _text(item) for key, item in value.items()}
    if len(result) != len(value) or set(result) - {
        "preview_cache_key",
        "callback_url",
        "user_id",
        "file_ext",
        "tenant_id",
    }:
        _blocked("invalid_payload")
    if result.get("user_id"):
        _ident(result["user_id"])
    if result.get("tenant_id"):
        _ident(result["tenant_id"])
    return result or None


class QueuedTaskInventoryReader:
    def __init__(self, session, *, repository=None, redis_connection=None):
        self.session = session
        self.repository = repository if repository is not None else UnificationTaskRepository()
        self.redis = redis_connection
        self._consumed = False

    async def _keys(self, pattern):
        """Support the real single-node and RedisCluster cursor shapes."""
        seen_keys, seen_cursors = set(), set()
        raw_cursor, values = _page(await self.redis.scan(match=pattern, count=BATCH))
        if type(raw_cursor) is dict:
            if not raw_cursor:
                _blocked("invalid_cluster_cursor")
            pending = []
            for name, cursor in raw_cursor.items():
                name, cursor = _text(name), _cursor(cursor)
                if cursor:
                    pending.append((name, cursor))
            cluster = True
        else:
            cursor = _cursor(raw_cursor)
            pending, cluster = ([(None, cursor)] if cursor else []), False
        while True:
            for value in values:
                key = _text(value)
                if not key.startswith(pattern[:-1]):
                    _blocked("unexpected_redis_key")
                if key not in seen_keys:
                    seen_keys.add(key)
                    yield key
            if not pending:
                break
            name, cursor = pending.pop()
            if (name, cursor) in seen_cursors:
                _blocked("repeated_redis_cursor")
            seen_cursors.add((name, cursor))
            kwargs = {"target_nodes": self.redis.get_node(node_name=name)} if cluster else {}
            raw_cursor, values = _page(await self.redis.scan(cursor=cursor, match=pattern, count=BATCH, **kwargs))
            if cluster:
                if type(raw_cursor) is not dict or set(raw_cursor) != {name}:
                    _blocked("invalid_cluster_cursor")
                cursor = _cursor(raw_cursor[name])
            else:
                cursor = _cursor(raw_cursor)
            if cursor:
                pending.append((name, cursor))

    async def _members(self, key, *, mapping=False):
        cursor, seen_cursors, seen_values = 0, set(), {}
        while True:
            result = await (
                self.redis.hscan(key, cursor=cursor, count=BATCH)
                if mapping
                else self.redis.sscan(key, cursor=cursor, count=BATCH)
            )
            raw_cursor, values = _page(result, mapping=mapping)
            for raw, value in values.items() if mapping else ((item, None) for item in values):
                ident = _ident(raw)
                value = _text(value) if mapping else None
                if ident in seen_values:
                    if seen_values[ident] != value:
                        _blocked("redis_membership_changed")
                    continue
                seen_values[ident] = value
                yield ident, value
            cursor = _cursor(raw_cursor)
            if not cursor:
                break
            if cursor in seen_cursors:
                _blocked("repeated_redis_cursor")
            seen_cursors.add(cursor)

    async def _type(self, key, expected):
        actual = _text(await self.redis.type(key))
        if actual == "none":
            return False  # Explicit absence/TTL expiry is not a transport error.
        if actual != expected:
            _blocked("redis_wrong_type")
        return True

    async def _contexts(self, identifiers):
        ids = tuple(dict.fromkeys(identifiers))
        facts = await self.repository.aget_file_facts(
            self.session, file_ids=tuple(dict.fromkeys(int(value) for value in ids))
        )
        by_id = {fact.file_id: fact for fact in facts if type(fact) is QueuedFileFact}
        if set(by_id) != {int(value) for value in ids} or len(by_id) != len(facts):
            _blocked("incomplete_file_facts")
        async with self.redis.pipeline(transaction=False) as pipeline:
            for ident in ids:
                pipeline.hgetall(PREFIX + "payload:" + ident)
            payloads = await pipeline.execute()
        routes = await self.redis.hmget(PREFIX + "inflight_queue", list(ids))
        if (
            type(payloads) is not list
            or type(routes) is not list
            or len(payloads) != len(ids)
            or len(routes) != len(ids)
        ):
            _blocked("incomplete_redis_batch")
        return {
            ident: (by_id[int(ident)], _payload(payload), _text(route) if route is not None else None)
            for ident, payload, route in zip(ids, payloads, routes, strict=True)
        }

    def _record(self, kind, task_id, ident, context, state, original):
        file, payload, route = context
        claim = int(payload["tenant_id"]) if payload and payload.get("tenant_id") else None
        if file.tenant_id is not None and (
            type(file.tenant_id) is not int or file.tenant_id <= 0 or file.tenant_id not in self.tenants
        ):
            _blocked("task_tenant_outside_run")
        if file.exists and claim is not None and file.tenant_id is not None and claim != file.tenant_id:
            _blocked("payload_tenant_mismatch")
        common = {
            "task_kind": kind,
            "task_id": task_id,
            "space_id": file.space_id,
            "file_id": int(ident),
            "document_id": file.document_id,
            "version_id": file.version_id,
            "state": state,
            "configuration_digest": task_digest({"payload": payload, "file_configuration": file.configuration_digest}),
            "record_digest": task_digest(
                {
                    "kind": kind,
                    "id": task_id,
                    "original": original,
                    "file": file.record_digest,
                    "payload": payload,
                    "route": route,
                }
            ),
        }
        if not file.exists or file.tenant_id is None:
            reason = (
                "file_missing" if not file.exists else "space_missing" if not file.space_exists else "unresolved_tenant"
            )
            return record_from_values("queued_task_orphan", **common, payload_tenant_id=claim, reason=reason)
        if not file.space_exists:
            common["state"] = "missing_space"
        return record_from_values("queued_task", **common, tenant_id=file.tenant_id)

    async def _records(self, kind, entries):
        contexts = await self._contexts(tuple(ident for _, ident, _ in entries))
        tokens = [None] * len(entries)
        if kind == "parse_lock":
            async with self.redis.pipeline(transaction=False) as pipeline:
                for task_id, _, _ in entries:
                    pipeline.get(task_id)
                tokens = await pipeline.execute()
            if type(tokens) is not list or len(tokens) != len(entries):
                _blocked("incomplete_lock_batch")
        for (task_id, ident, original), token in zip(entries, tokens, strict=True):
            context = contexts[ident]
            if kind == "scheduler_queue":
                state = "queued" if context[1] else "queued_payload_missing"
            elif kind == "inflight":
                state = "inflight_confirmed" if context[2] is not None else "inflight_unconfirmed"
            elif kind == "dispatch":
                if original != context[2]:
                    _blocked("redis_dispatch_changed")
                state = "dispatch_confirmed"
            elif kind == "parse_lock":
                original = task_digest(_text(token) if token is not None else None)
                state = "parse_lock_present" if token is not None else "parse_lock_missing"
            else:
                state = "payload_present" if context[1] else "payload_missing"
            yield self._record(kind, task_id, ident, context, state, original)

    async def _redis_facts(self):
        for kind, suffix, expected in (
            ("scheduler_queue", "queue:", "list"),
            ("payload", "payload:", "hash"),
            ("inflight", "inflight:", "set"),
            ("parse_lock", "parse_lock:", "string"),
        ):
            entries = []
            async for key in self._keys(PREFIX + suffix + "*"):
                _ident(key[len(PREFIX + suffix) :])
                if not await self._type(key, expected):
                    continue
                if kind == "scheduler_queue":
                    offset = 0
                    while True:
                        values = await self.redis.lrange(key, offset, offset + BATCH - 1)
                        if type(values) is not list or len(values) > BATCH:
                            _blocked("invalid_queue_page")
                        batch = [
                            (f"{key}:{offset + index}:{_ident(value)}", _ident(value), offset + index)
                            for index, value in enumerate(values)
                        ]
                        if batch:
                            async for record in self._records(kind, batch):
                                yield record
                        if len(values) < BATCH:
                            break
                        offset += len(values)
                elif kind == "inflight":
                    async for ident, _ in self._members(key):
                        entries.append((f"{key}:{ident}", ident, key))
                        if len(entries) == BATCH:
                            async for record in self._records(kind, entries):
                                yield record
                            entries = []
                else:
                    ident = _ident(key[len(PREFIX + suffix) :])
                    entries.append((key, ident, key))
                if len(entries) >= BATCH:
                    async for record in self._records(kind, entries):
                        yield record
                    entries = []
            if entries:
                async for record in self._records(kind, entries):
                    yield record
        key, entries = PREFIX + "inflight_queue", []
        if await self._type(key, "hash"):
            async for ident, queue in self._members(key, mapping=True):
                entries.append((f"{key}:{ident}", ident, queue))
                if len(entries) == BATCH:
                    async for record in self._records("dispatch", entries):
                        yield record
                    entries = []
        if entries:
            async for record in self._records("dispatch", entries):
                yield record

    async def aiter_facts(self, *, tenant_ids: tuple[int, ...]):
        if (
            self._consumed
            or type(tenant_ids) is not tuple
            or not tenant_ids
            or any(type(tenant) is not int or tenant <= 0 for tenant in tenant_ids)
            or tuple(sorted(set(tenant_ids))) != tenant_ids
        ):
            _blocked("complete_tenant_set_required")
        self._consumed, self.tenants = True, frozenset(tenant_ids)
        try:
            for name in ("jobs", "items", "delete_jobs"):
                after = None
                while True:
                    page = await getattr(self.repository, "alist_" + name)(self.session, after_id=after, limit=BATCH)
                    if type(page.items) is not tuple or len(page.items) > BATCH:
                        _blocked("invalid_sql_page")
                    for row in page.items:
                        if type(row) is not TaskFact or row.tenant_id not in self.tenants:
                            _blocked("task_tenant_outside_run")
                        yield record_from_values("queued_task", **asdict(row))
                    if page.next_after is None:
                        break
                    if (
                        type(page.next_after) is not str
                        or not page.next_after
                        or (after is not None and page.next_after <= after)
                    ):
                        _blocked("invalid_sql_cursor")
                    after = page.next_after
            if self.redis is None:
                self.redis = (await get_redis_client()).async_connection
            async for record in self._redis_facts():
                yield record
        except KnowledgeOperationPlanConflictError:
            raise
        except Exception as error:
            raise KnowledgeOperationPlanConflictError(reason="migration_tasks_read_failed") from error
