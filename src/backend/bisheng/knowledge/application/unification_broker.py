"""Raw Redis broker facts. Never create a Kombu channel or consume a task."""

import asyncio
import hashlib
import math
from dataclasses import replace
from types import SimpleNamespace

from loguru import logger

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.knowledge.application.unification_broker_codec import (
    BrokerReadConfiguration,
    decode_broker_message,
    decode_unacked_message,
)
from bisheng.knowledge.application.unification_inventory_codec import record_from_values
from bisheng.knowledge.application.unification_tasks import QueuedTaskInventoryReader, _cursor, _text
from bisheng.knowledge.domain.repositories.unification_task_repository import (
    UnificationTaskRepository,
    _scope,
    task_digest,
)
from bisheng.resource_reference.application.contracts import TransactionIdentity

MAX_REPLY_BYTES = 64 * 1024 * 1024
TARGET_BATCH = 200


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason=f"migration_broker_{reason}")


def _bytes(value):
    if type(value) is str:
        return value.encode("utf-8")
    if type(value) is not bytes:
        _blocked("invalid_raw_message")
    return value


def _reply_budget(value):
    def size(item):
        if item is None:
            return 0
        if type(item) in (str, bytes):
            return len(_bytes(item))
        if type(item) in (int, float):
            return len(str(item))
        if type(item) is dict:
            return sum(size(key) + size(value) for key, value in item.items())
        if type(item) in (list, tuple):
            return sum(size(value) for value in item)
        _blocked("invalid_redis_reply")

    # redis-py has already received this reply. This is an acceptance budget,
    # not a preallocation guarantee for a malformed/oversized native response.
    if size(value) > MAX_REPLY_BYTES:
        _blocked("reply_budget")


class _ScanProxy:
    def __init__(self, owner, wanted=None):
        self.owner, self.wanted = owner, wanted

    async def scan(self, **kwargs):
        # Escape only the literal configured prefix at the native command.
        # The shared scanner still validates returned keys against its original
        # unescaped prefix; no Redis glob token becomes migration scope.
        prefix = self.owner.configuration.global_keyprefix
        pattern = kwargs["match"]
        if not pattern.startswith(prefix):
            _blocked("invalid_scan_prefix")
        literal = "".join("\\" + char if char in "*?[]\\" else char for char in prefix)
        kwargs["match"] = literal + pattern[len(prefix) :]
        if self.wanted is not None:
            kwargs["_type"] = self.wanted
        return await self.owner._call(self.owner.redis.scan, **kwargs)

    def get_node(self, **kwargs):
        return self.owner.redis.get_node(**kwargs)


class RedisBrokerInventoryReader:
    def __init__(self, session, *, repository=None, configuration=None, redis_connection=None):
        self.session = session
        self.repository = repository if repository is not None else UnificationTaskRepository()
        self.configuration, self.redis = configuration, redis_connection
        self._owned_clients, self._consumed, self._closed = [], False, False

    async def _open(self):
        from redis.asyncio import Redis
        from redis.asyncio.sentinel import Sentinel

        options = self.configuration.connection_options()
        keepalive = options.get("socket_keepalive_options")
        if keepalive:
            options["socket_keepalive_options"] = {int(key): value for key, value in keepalive.items()}
        if self.configuration.mode != "sentinel":
            client = Redis.from_url(options.pop("url"), **options)
        else:
            hosts, master = options.pop("sentinels"), options.pop("master_name")
            monitor = Sentinel(hosts, **options)
            self._owned_clients.extend(monitor.sentinels)
            client = monitor.master_for(master)
        self._owned_clients.append(client)
        return client

    async def aclose(self):
        self._closed = True
        clients, self._owned_clients = self._owned_clients, []
        if not clients:
            return

        async def close_all():
            error = None
            for client in clients:
                try:
                    await client.aclose()
                except Exception as failure:
                    error = error or failure
                    logger.warning("Read-only broker client cleanup failed ({})", type(failure).__name__)
            if error is not None:
                raise KnowledgeOperationPlanConflictError(reason="migration_broker_close_failed") from error

        closing, cancelled = asyncio.create_task(close_all()), None
        while not closing.done():
            try:
                await asyncio.shield(closing)
            except asyncio.CancelledError as error:
                cancelled = error
        closing.result()
        if cancelled is not None:
            raise cancelled

    def _current(self):
        if self._closed or get_current_tenant_id() != self._tenant or is_tenant_filter_bypassed():
            _blocked("original_scope_changed")
        try:
            self._transaction.assert_current(self.session)
        except (ValueError, TypeError):
            _blocked("original_transaction_changed")

    async def _call(self, function, *args, **kwargs):
        self._current()
        value = await function(*args, **kwargs)
        self._current()
        _reply_budget(value)
        return value

    async def _keys(self, pattern, wanted=None):
        # Reuse the tested single/cluster cursor progression, not the scheduler.
        owner = SimpleNamespace(redis=_ScanProxy(self, wanted))
        async for key in QueuedTaskInventoryReader._keys(owner, pattern):
            yield key

    async def _type(self, key, expected):
        actual = _text(await self._call(self.redis.type, key))
        if actual not in {expected, "none"}:
            _blocked("redis_wrong_type")
        return actual == expected

    async def _walk(self, method, key, *, mapping=False, count=200, decode=None):
        cursor, cursors, seen = 0, set(), {}
        while True:
            result = await self._call(method, key, cursor=cursor, count=count)
            if type(result) not in (list, tuple) or len(result) != 2:
                _blocked("invalid_redis_page")
            next_cursor, values = result
            if (mapping and type(values) is not dict) or (not mapping and type(values) is not list):
                _blocked("invalid_redis_page")
            for key_value, value in values.items() if mapping else ((item, None) for item in values):
                if type(key_value) in (list, tuple):  # ZSCAN (member, score)
                    if len(key_value) != 2:
                        _blocked("invalid_redis_page")
                    key_value, value = key_value
                ident = _text(key_value)
                if decode is not None:
                    value = decode(value)
                    fingerprint = value[-1]
                else:
                    fingerprint = task_digest(value)
                if ident in seen:
                    if seen[ident] != fingerprint:
                        _blocked("broker_changed_during_read")
                    continue
                seen[ident] = fingerprint
                yield ident, value
            cursor = _cursor(next_cursor)
            if not cursor:
                break
            if cursor in cursors:
                _blocked("repeated_redis_cursor")
            cursors.add(cursor)

    def _score(self, value):
        if value is not None and (type(value) not in (float, int) or not math.isfinite(value)):
            _blocked("invalid_unacked_score")
        return value

    async def _packets(self):
        config = self.configuration
        prefix, queues = config.global_keyprefix, set(config.queues)
        async for key in self._keys(prefix + "_kombu.binding.*"):
            if await self._type(key, "set"):
                async for value, _ in self._walk(self.redis.sscan, key):
                    parts = value.split(config.sep)
                    if len(parts) != 3 or not parts[2]:
                        _blocked("invalid_binding")
                    queues.add(parts[2])
        for queue in queues:
            for priority in config.priority_steps:
                await self._type(prefix + queue + (config.sep + str(priority) if priority else ""), "list")
        async for key in self._keys(prefix + "*", "list"):
            if not await self._type(key, "list"):
                continue
            base, _, priority = key[len(prefix) :].rpartition(config.sep)
            required = key[len(prefix) :] in queues or (priority.isdecimal() and base in queues)
            offset = 0
            while True:
                values = await self._call(self.redis.lrange, key, offset, offset)
                if type(values) is not list or len(values) > 1:
                    _blocked("invalid_queue_page")
                if not values:
                    break
                message = decode_broker_message(values[0], required=required)
                if message is not None:
                    yield message, {"location": "queued", "key": task_digest(key), "offset": offset}
                offset += 1
        unacked, index, mutex = (
            prefix + name for name in (config.unacked_key, config.unacked_index_key, config.unacked_mutex_key)
        )
        mutex_digest = task_digest(None)
        if await self._type(mutex, "string"):
            value = await self._call(self.redis.get, mutex)
            mutex_digest = hashlib.sha256(_bytes(value)).hexdigest() if value is not None else task_digest(None)
        has_hash, has_index = await self._type(unacked, "hash"), await self._type(index, "zset")
        tags = set()
        if has_hash:
            async for tag, decoded in self._walk(
                self.redis.hscan, unacked, mapping=True, count=1, decode=decode_unacked_message
            ):
                tags.add(tag)
                message, exchange, routing, _ = decoded
                score = self._score(await self._call(self.redis.zscore, index, tag)) if has_index else None
                if message is not None:
                    yield (
                        message,
                        {
                            "location": "unacked",
                            "tag": task_digest(tag),
                            "exchange": task_digest(exchange),
                            "routing": task_digest(routing),
                            "score": score,
                            "mutex": mutex_digest,
                        },
                    )
        if has_index:
            async for tag, score in self._walk(self.redis.zscan, index):
                if tag in tags:
                    continue
                self._score(score)
                raw = await self._call(self.redis.hget, unacked, tag) if has_hash else None
                if raw is None:
                    yield None, {"location": "unacked", "tag": task_digest(tag), "score": score, "mutex": mutex_digest}
                else:
                    _blocked("broker_changed_during_read")

    async def _lookup(self, name, parameter, ids):
        unique, output = tuple(dict.fromkeys(ids)), {}
        for offset in range(0, len(unique), TARGET_BATCH):
            batch = unique[offset : offset + TARGET_BATCH]
            self._current()
            rows = await getattr(self.repository, name)(self.session, **{parameter: batch})
            self._current()
            for row in rows:
                ident = row.file_id if name == "aget_file_facts" else row.target_id
                if ident not in batch or ident in output:
                    _blocked("invalid_target_facts")
                output[ident] = row
        if set(output) != set(unique):
            _blocked("incomplete_target_facts")
        return output

    async def _preload(self, packets):
        ids = {name: [] for name in ("files", "spaces", "jobs", "delete_jobs", "qa")}
        for message, _ in packets:
            kind = "files" if message.scope_kind == "move" else message.scope_kind
            if kind != "global":
                ids[kind].extend(message.target_ids)
            ids["spaces"].extend(value for value in (message.space_id, message.source_space_id) if value is not None)
        methods = {
            "files": ("aget_file_facts", "file_ids"),
            "spaces": ("aget_space_facts", "space_ids"),
            "jobs": ("aget_job_facts", "job_ids"),
            "delete_jobs": ("aget_delete_job_facts", "job_ids"),
            "qa": ("aget_qa_facts", "qa_ids"),
        }
        return {kind: await self._lookup(*methods[kind], values) for kind, values in ids.items()}

    def _observe(self, message, facts, summary):
        def touch(fact):
            summary["digest"].update(fact.record_digest.encode())
            if not fact.exists:
                summary["missing"] = True
                return
            tenant = fact.tenant_id
            if type(tenant) is not int or tenant not in self._tenants:
                _blocked("target_tenant_outside_run")
            if message.header_tenant_id is not None and tenant != message.header_tenant_id:
                _blocked("header_tenant_mismatch")
            summary["tenants"].add(tenant)
            if len(summary["tenants"]) > 1:
                _blocked("cross_tenant_targets")

        declared = facts["spaces"].get(message.space_id)
        if declared is not None and message.scope_kind != "spaces":
            touch(declared)
        kind = "files" if message.scope_kind == "move" else message.scope_kind
        if kind != "global":
            for ident in message.target_ids:
                fact = facts[kind][ident]
                if (
                    kind == "files"
                    and not fact.exists
                    and message.task_name.endswith("delete_knowledge_file_celery")
                    and declared is not None
                    and declared.exists
                ):
                    summary["digest"].update(
                        fact.record_digest.encode()
                    )  # Valid old cleanup, anchored by the real Root.
                    continue
                touch(fact)
                if not fact.exists:
                    continue
                summary["space"] = message.space_id if message.space_id is not None else fact.space_id
                if kind == "files":
                    if fact.file_type != 1:
                        _blocked("invalid_file_target")
                    if not fact.space_exists:
                        summary["missing"] = True
                    if message.space_id is not None and fact.space_id != message.space_id:
                        _blocked("file_space_mismatch")
                    summary["file"] = fact
                elif kind == "spaces" and message.expected_revision is not None:
                    if (
                        fact.revision != message.expected_revision
                        or fact.index_generation != message.expected_generation
                        or fact.operation_id != message.operation_id
                    ):
                        summary["obsolete"] = True
                elif kind == "jobs" and (fact.revision != message.expected_revision or fact.state == "obsolete"):
                    summary["obsolete"] = True
        if message.source_space_id is not None and message.scope_kind != "spaces":
            touch(facts["spaces"][message.source_space_id])

    def _record(self, message, locator, summary):
        if message is None:
            identity, name, state, tenant, claim = (
                "metadata:" + locator["tag"],
                None,
                "unacked_metadata_orphan",
                None,
                None,
            )
        else:
            identity, name, claim = message.message_id, message.task_name, message.header_tenant_id
            state = (
                "global_control"
                if message.scope_kind == "global"
                else "target_missing"
                if summary["missing"]
                else "legacy_requires_reissue"
                if message.legacy_requires_reissue
                else "obsolete"
                if summary["obsolete"]
                else locator["location"]
            )
            tenant = None if state in {"global_control", "target_missing"} else next(iter(summary["tenants"]), None)
        file = (
            summary["file"]
            if message is not None and len(message.target_ids) == 1 and message.scope_kind in {"files", "move"}
            else None
        )
        return record_from_values(
            "broker_task",
            tenant_id=tenant,
            task_kind=name,
            task_id=f"{identity}:{locator['location']}:{task_digest(locator)}",
            space_id=summary["space"],
            file_id=file.file_id
            if file
            else (
                message.target_ids[0]
                if message is not None and message.scope_kind in {"files", "move"} and len(message.target_ids) == 1
                else None
            ),
            document_id=file.document_id if file else None,
            version_id=file.version_id if file else None,
            header_tenant_id=claim,
            state=state,
            configuration_digest=message.configuration_digest if message is not None else task_digest(None),
            record_digest=task_digest(
                {
                    "raw": message.raw_digest if message is not None else None,
                    "locator": locator,
                    "facts": summary["digest"].hexdigest(),
                    "broker": self.configuration.fingerprint,
                }
            ),
        )

    @staticmethod
    def _summary(message):
        return {
            "digest": hashlib.sha256(),
            "missing": False,
            "obsolete": False,
            "tenants": set(),
            "space": message.space_id if message is not None else None,
            "file": None,
        }

    async def _records(self, packets):
        facts = await self._preload(packets)
        for message, locator in packets:
            summary = self._summary(message)
            self._observe(message, facts, summary)
            yield self._record(message, locator, summary)

    async def aiter_facts(self, *, tenant_ids):
        if (
            self._consumed
            or type(tenant_ids) is not tuple
            or not tenant_ids
            or any(type(tid) is not int or tid <= 0 for tid in tenant_ids)
            or tuple(sorted(set(tenant_ids))) != tenant_ids
        ):
            _blocked("complete_tenant_set_required")
        _scope(self.session)
        self._tenant, self._transaction = get_current_tenant_id(), TransactionIdentity.capture(self.session)
        self._consumed, self._tenants = True, frozenset(tenant_ids)
        primary, pending, weight = None, [], 0
        try:
            if self.configuration is None:
                from bisheng.common.services.config_service import settings
                from bisheng.worker.main import bisheng_celery

                self.configuration = BrokerReadConfiguration.from_conf(
                    bisheng_celery.conf, ocr_queue=settings.knowledge_file_worker.ocr_queue
                )
            if type(self.configuration) is not BrokerReadConfiguration:
                _blocked("real_configuration_required")
            if self.redis is None:
                self.redis = await self._open()
            async for message, locator in self._packets():
                self._current()
                slots = max(len(message.target_ids), 1) if message is not None else 1
                if pending and (weight + slots > TARGET_BATCH or message is None):
                    async for record in self._records(pending):
                        yield record
                    pending, weight = [], 0
                if message is None:
                    yield self._record(None, locator, self._summary(None))
                elif slots > TARGET_BATCH:
                    summary = self._summary(message)
                    for offset in range(0, len(message.target_ids), TARGET_BATCH):
                        part = replace(message, target_ids=message.target_ids[offset : offset + TARGET_BATCH])
                        self._observe(part, await self._preload([(part, locator)]), summary)
                    yield self._record(message, locator, summary)
                else:
                    pending.append((message, locator))
                    weight += slots
            if pending:
                async for record in self._records(pending):
                    yield record
            self._current()
        except BaseException as error:
            primary = error
            if isinstance(error, KnowledgeOperationPlanConflictError) or not isinstance(error, Exception):
                raise
            raise KnowledgeOperationPlanConflictError(reason="migration_broker_read_failed") from error
        finally:
            try:
                await self.aclose()
            except BaseException as error:
                if primary is None or (
                    isinstance(error, asyncio.CancelledError) and not isinstance(primary, asyncio.CancelledError)
                ):
                    raise
                logger.warning("Read-only broker cleanup preserved primary failure ({})", type(error).__name__)
