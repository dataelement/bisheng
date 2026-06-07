# File Parse Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split knowledge-file parsing into an OCR queue + a non-OCR queue with independent worker concurrency, and add a per-user fair scheduler so one heavy uploader cannot starve other users.

**Architecture:** Two feature flags wrap the changes. (1) `ocr_queue_enabled` routes Celery tasks to `ocr_celery` or `knowledge_celery` based on file extension + loader configuration; `run_celery.py` reads `BISHENG_CELERY_MODE` so OCR / non-OCR workers can be started separately. (2) `fair_scheduler_enabled` replaces direct `parse_knowledge_file_celery.delay()` with a Redis "virtual queue" (per-user lists + inflight sets, all sharing the `{bisheng_fs}` hash tag), driven by Lua scripts for atomicity, a distributed-lock-protected dispatch round triggered by upload/complete events plus a 30-second Beat fallback, and a 5-minute reconcile task that repairs Redis vs DB drift.

**Tech Stack:** Python 3.10 + Celery (existing `bisheng_celery`) + Redis (existing `RedisClient` from `bisheng.core.cache`) + Pydantic Settings (`bisheng.core.config.settings`) + Lua (5 scripts, run via `EVAL`).

**Reference spec:** [`docs/archive/legacy-sdd/specs/2026-05-20-file-parse-scheduler-design.md`](../specs/2026-05-20-file-parse-scheduler-design.md)

---

## File Structure

**New files:**
- `src/backend/bisheng/worker/knowledge/scheduler.py` — `FileScheduler` (Lua wrappers, dispatch round, reconcile), `trigger_dispatch_task`, `reconcile_file_scheduler_task` Celery tasks, `needs_ocr_queue` / `decide_queue` helpers.
- `src/backend/bisheng/worker/knowledge/lua_scripts.py` — All five Lua scripts as Python string constants (enqueue / dispatch_one / rollback_dispatch / complete_file / release_lock).
- `src/backend/test/knowledge/test_file_scheduler_lua.py` — Lua atomicity tests using a real Redis (`fakeredis` is insufficient — see Task 3 step 1).
- `src/backend/test/knowledge/test_file_scheduler_dispatch.py` — Dispatch / rollback / reconcile flows.
- `src/backend/test/knowledge/test_decide_queue.py` — OCR routing decision.
- `src/backend/test/knowledge/test_file_worker_complete_hook.py` — `finally` callback wiring.

**Modified files:**
- `src/backend/bisheng/core/config/settings.py` — Add `KnowledgeFileWorkerConf`, `FairSchedulerConf`; expose on `Settings`; add Beat entries in `CeleryConf.validate`.
- `src/backend/bisheng/worker/knowledge/file_worker.py` — `parse_knowledge_file_celery.finally` calls `FileScheduler.complete_file` + `trigger_dispatch_task.delay()`; `retry_knowledge_file_celery` re-enqueues to the virtual queue when fair scheduler is on.
- `src/backend/bisheng/knowledge/domain/services/knowledge_service.py` — `process_knowledge_file` / `aprocess_knowledge_file` route through `FileScheduler.enqueue_or_dispatch`.
- `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` — same swap at the two dispatch sites (upload + retry).
- `src/backend/bisheng/knowledge/domain/services/knowledge_utils.py` — `process_rebuild_file` / `process_retry_files` use new dispatch helper (logic still lives in the celery task, but config-aware).
- `src/backend/bisheng/run_celery.py` — Read `BISHENG_CELERY_MODE` (`all` / `ocr` / `file`) and `BISHENG_CELERY_CONCURRENCY`.
- `src/backend/bisheng/worker/__init__.py` — Export `trigger_dispatch_task`, `reconcile_file_scheduler_task` so Celery auto-discovers them.

---

## Conventions used by this plan

- Run commands from `src/backend/`.
- Tests live under `src/backend/test/knowledge/`; `asyncio_mode=auto` is set, so async tests need no `@pytest.mark.asyncio`.
- Format & lint after each edit: `uv run ruff format <path>` then `uv run ruff check --fix <path>`.
- Lua key prefix is the literal string `{bisheng_fs}:` so all keys land in one Redis Cluster slot. Do **not** parameterize the prefix in tests or code — keep it fixed.
- All new modules import the existing sync Redis connection via `get_redis_client_sync().connection` (a `redis.StrictRedis` or `RedisCluster`). Lua runs via `connection.eval(script, numkeys, *keys_and_args)` or via `connection.register_script(...)`.

---

### Task 1: Configuration model + Settings wiring

**Files:**
- Modify: `src/backend/bisheng/core/config/settings.py:136-237` (insert new classes before `LinsightConf`, then add field on `Settings`)
- Test: `src/backend/test/knowledge/test_file_scheduler_config.py` (new)

- [ ] **Step 1: Write failing test for config defaults & validation**

Create `src/backend/test/knowledge/test_file_scheduler_config.py`:

```python
import pytest

from bisheng.core.config.settings import (
    FairSchedulerConf,
    KnowledgeFileWorkerConf,
)


def test_knowledge_file_worker_conf_defaults():
    conf = KnowledgeFileWorkerConf()
    assert conf.ocr_queue_enabled is False
    assert conf.ocr_queue == "ocr_celery"
    assert conf.fair_scheduler_enabled is False
    assert conf.fair_scheduler.dispatch_interval_seconds == 30
    assert conf.fair_scheduler.dispatch_lock_ttl_seconds == 24
    assert conf.fair_scheduler.max_per_user_inflight == 1
    assert conf.fair_scheduler.user_overrides == {}
    assert conf.fair_scheduler.inflight_ttl_seconds == 7200
    assert conf.fair_scheduler.reconcile_interval_seconds == 300


def test_fair_scheduler_lock_ttl_must_be_less_than_interval():
    with pytest.raises(ValueError):
        FairSchedulerConf(dispatch_interval_seconds=30, dispatch_lock_ttl_seconds=30)


def test_fair_scheduler_max_per_user_inflight_minimum_one():
    with pytest.raises(ValueError):
        FairSchedulerConf(max_per_user_inflight=0)


def test_fair_scheduler_user_overrides_accepts_string_ids():
    conf = FairSchedulerConf(user_overrides={"123": 3, "456": 5})
    assert conf.limit_for("123") == 3
    assert conf.limit_for("456") == 5
    assert conf.limit_for("999") == conf.max_per_user_inflight
```

- [ ] **Step 2: Run test to confirm failure**

```bash
uv run pytest test/knowledge/test_file_scheduler_config.py -v
```
Expected: `ImportError: cannot import name 'KnowledgeFileWorkerConf'`.

- [ ] **Step 3: Add the two config classes in `settings.py`**

Insert immediately above `class LinsightConf` (around line 239):

```python
class FairSchedulerConf(BaseModel):
    """Fair scheduler runtime configuration."""

    dispatch_interval_seconds: int = Field(default=30, ge=1)
    dispatch_lock_ttl_seconds: int = Field(default=24, ge=1)
    max_per_user_inflight: int = Field(default=1, ge=1)
    user_overrides: Dict[str, int] = Field(default_factory=dict)
    inflight_ttl_seconds: int = Field(default=7200, ge=60)
    reconcile_interval_seconds: int = Field(default=300, ge=30)

    @model_validator(mode="after")
    def _validate(self):
        if self.dispatch_lock_ttl_seconds >= self.dispatch_interval_seconds:
            raise ValueError(
                "dispatch_lock_ttl_seconds must be strictly less than dispatch_interval_seconds"
            )
        for user_id, limit in self.user_overrides.items():
            if limit < 1:
                raise ValueError(
                    f"user_overrides[{user_id}] must be >= 1, got {limit}"
                )
        return self

    def limit_for(self, user_id: str) -> int:
        return self.user_overrides.get(str(user_id), self.max_per_user_inflight)


class KnowledgeFileWorkerConf(BaseModel):
    """Knowledge file worker (parse pipeline) configuration."""

    ocr_queue_enabled: bool = Field(default=False)
    ocr_queue: str = Field(default="ocr_celery")
    fair_scheduler_enabled: bool = Field(default=False)
    fair_scheduler: FairSchedulerConf = Field(default_factory=FairSchedulerConf)
```

Then on `Settings` (after `celery_task: CeleryConf = CeleryConf()` around line 479) add:

```python
    knowledge_file_worker: KnowledgeFileWorkerConf = KnowledgeFileWorkerConf()
```

- [ ] **Step 4: Re-run test, expect pass**

```bash
uv run pytest test/knowledge/test_file_scheduler_config.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Format / lint / commit**

```bash
uv run ruff format bisheng/core/config/settings.py test/knowledge/test_file_scheduler_config.py
uv run ruff check --fix bisheng/core/config/settings.py test/knowledge/test_file_scheduler_config.py
git add bisheng/core/config/settings.py test/knowledge/test_file_scheduler_config.py
git commit -m "feat(scheduler): add KnowledgeFileWorkerConf + FairSchedulerConf settings"
```

---

### Task 2: OCR queue routing helper (`needs_ocr_queue` / `decide_queue`)

**Files:**
- Create: `src/backend/bisheng/worker/knowledge/scheduler.py` (initial skeleton — only routing helpers in this task)
- Test: `src/backend/test/knowledge/test_decide_queue.py` (new)

- [ ] **Step 1: Write failing test**

Create `src/backend/test/knowledge/test_decide_queue.py`:

```python
from unittest.mock import patch

import pytest

from bisheng.worker.knowledge.scheduler import (
    decide_queue,
    needs_ocr_queue,
)


@pytest.fixture
def loader_configured():
    with patch(
        "bisheng.worker.knowledge.scheduler._loader_configured",
        return_value=True,
    ) as m:
        yield m


@pytest.fixture
def loader_not_configured():
    with patch(
        "bisheng.worker.knowledge.scheduler._loader_configured",
        return_value=False,
    ) as m:
        yield m


@pytest.mark.parametrize("ext", ["png", "jpg", "jpeg", "bmp", "JPG", "PNG"])
def test_images_always_need_ocr(loader_not_configured, ext):
    assert needs_ocr_queue(ext) is True


def test_pdf_needs_ocr_only_when_loader_configured(loader_configured):
    assert needs_ocr_queue("pdf") is True


def test_pdf_skips_ocr_when_loader_missing(loader_not_configured):
    assert needs_ocr_queue("pdf") is False


def test_other_extensions_never_need_ocr(loader_configured):
    assert needs_ocr_queue("docx") is False
    assert needs_ocr_queue("txt") is False
    assert needs_ocr_queue("") is False


def test_decide_queue_disabled_returns_knowledge_celery(loader_configured):
    with patch(
        "bisheng.worker.knowledge.scheduler._ocr_queue_enabled",
        return_value=False,
    ):
        assert decide_queue("a.pdf") == "knowledge_celery"
        assert decide_queue("a.png") == "knowledge_celery"


def test_decide_queue_enabled_routes_by_extension(loader_configured):
    with patch(
        "bisheng.worker.knowledge.scheduler._ocr_queue_enabled",
        return_value=True,
    ):
        assert decide_queue("invoice.pdf") == "ocr_celery"
        assert decide_queue("photo.PNG") == "ocr_celery"
        assert decide_queue("notes.txt") == "knowledge_celery"
        assert decide_queue("no_extension") == "knowledge_celery"
```

- [ ] **Step 2: Run and confirm failure**

```bash
uv run pytest test/knowledge/test_decide_queue.py -v
```
Expected: `ImportError`.

- [ ] **Step 3: Create `scheduler.py` skeleton with routing helpers**

Create `src/backend/bisheng/worker/knowledge/scheduler.py`:

```python
"""File parse scheduler — OCR routing helpers and (later tasks) fair dispatch."""

from __future__ import annotations

import os
from typing import Optional

from bisheng.common.services.config_service import settings

KNOWLEDGE_QUEUE = "knowledge_celery"
_IMAGE_EXTS = frozenset({"png", "jpg", "jpeg", "bmp"})


def _ocr_queue_enabled() -> bool:
    return bool(settings.knowledge_file_worker.ocr_queue_enabled)


def _loader_configured() -> bool:
    """True when at least one external OCR/ETL service URL is set.

    KnowledgeConf is DB-stored and fetched via `settings.get_knowledge()`,
    which is cached in Redis for 100s — cheap to call per dispatch.
    """
    try:
        knowledge_conf = settings.get_knowledge()
    except Exception:
        logger.exception("file_scheduler: failed to load KnowledgeConf; treating as no OCR")
        return False
    return bool(
        (knowledge_conf.etl4lm.url or "")
        or (knowledge_conf.mineru.url or "")
        or (knowledge_conf.paddle_ocr.url or "")
    )


def _extract_ext(file_name: str) -> str:
    _, _, ext = file_name.rpartition(".")
    if ext == file_name:  # no dot → no extension
        return ""
    return ext.lower()


def needs_ocr_queue(file_ext_or_name: str) -> bool:
    ext = file_ext_or_name.lower()
    if "." in ext:
        ext = _extract_ext(ext)
    if ext in _IMAGE_EXTS:
        return True
    if ext == "pdf":
        return _loader_configured()
    return False


def decide_queue(file_name_or_ext: str) -> str:
    """Return the Celery queue name for a given file.

    Always returns ``knowledge_celery`` when the OCR queue feature flag is
    off, so callers can route unconditionally.
    """
    if not _ocr_queue_enabled():
        return KNOWLEDGE_QUEUE
    return settings.knowledge_file_worker.ocr_queue if needs_ocr_queue(file_name_or_ext) else KNOWLEDGE_QUEUE
```

**Note about `_loader_configured`**: the real config object is `settings.knowledge_conf` if present, otherwise `settings.knowledge` (a `KnowledgeConf` instance in newer settings versions). Inspect `bisheng/core/config/settings.py` to confirm — at the time of writing, the active field is `settings.knowledge_conf` (search for `KnowledgeConf` use in `bisheng/knowledge/rag/base_file_pipeline.py`). If the field name is different, use `settings.knowledge_conf` directly and drop the `getattr` fallback. The test mocks `_loader_configured`, so the helper's internals don't need to be perfect to pass tests in this task, but they **must work in production**.

- [ ] **Step 4: Run and confirm pass**

```bash
uv run pytest test/knowledge/test_decide_queue.py -v
```
Expected: 8 passed.

- [ ] **Step 5: Verify `_loader_configured` against real settings shape**

```bash
uv run python -c "from bisheng.common.services.config_service import settings; print(type(getattr(settings, 'knowledge_conf', None)), type(getattr(settings, 'knowledge', None)))"
```

Adjust `_loader_configured` if needed so that production code reads from the real `KnowledgeConf` instance, then add this test:

```python
def test_loader_configured_reads_real_settings(monkeypatch):
    from bisheng.worker.knowledge import scheduler as s
    from bisheng.common.services.config_service import settings as real_settings

    # If the real settings exposes a KnowledgeConf, _loader_configured must
    # return True when any URL is set and False when all are blank.
    knowledge_conf = getattr(real_settings, "knowledge_conf", None) or getattr(real_settings, "knowledge", None)
    if knowledge_conf is None or not hasattr(knowledge_conf, "etl4lm"):
        return  # nothing to assert
    monkeypatch.setattr(knowledge_conf.etl4lm, "url", "")
    monkeypatch.setattr(knowledge_conf.mineru, "url", "")
    monkeypatch.setattr(knowledge_conf.paddle_ocr, "url", "")
    assert s._loader_configured() is False
    monkeypatch.setattr(knowledge_conf.etl4lm, "url", "http://etl4lm.local")
    assert s._loader_configured() is True
```

Re-run the test file; expect 9 passed.

- [ ] **Step 6: Format / lint / commit**

```bash
uv run ruff format bisheng/worker/knowledge/scheduler.py test/knowledge/test_decide_queue.py
uv run ruff check --fix bisheng/worker/knowledge/scheduler.py test/knowledge/test_decide_queue.py
git add bisheng/worker/knowledge/scheduler.py test/knowledge/test_decide_queue.py
git commit -m "feat(scheduler): add needs_ocr_queue + decide_queue routing helpers"
```

---

### Task 3: Lua scripts and atomic Redis ops

**Files:**
- Create: `src/backend/bisheng/worker/knowledge/lua_scripts.py`
- Modify: `src/backend/bisheng/worker/knowledge/scheduler.py` (add `FileScheduler` class with Lua wrappers)
- Test: `src/backend/test/knowledge/test_file_scheduler_lua.py`

**Important:** these tests **must hit a real Redis** (single-node is fine; we don't need cluster locally because the hash tag keeps everything in one slot anyway). Use the existing test fixture pattern. If no Redis fixture exists, gate the test with `pytest.importorskip("redis")` + `pytest.skip(...)` when `localhost:6379` is unreachable. Do **not** use `fakeredis` — its Lua semantics differ from real Redis.

- [ ] **Step 1: Write failing test scaffold + smoke test**

Create `src/backend/test/knowledge/test_file_scheduler_lua.py`:

```python
import socket

import pytest
import redis

from bisheng.worker.knowledge.scheduler import FileScheduler


def _redis_reachable(host: str = "localhost", port: int = 6379) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_reachable(), reason="Local Redis required for Lua tests"
)


@pytest.fixture
def redis_conn():
    conn = redis.StrictRedis(host="localhost", port=6379, db=15, decode_responses=True)
    # Clean every {bisheng_fs}: key before & after each test.
    for key in conn.keys("{bisheng_fs}:*"):
        conn.delete(key)
    yield conn
    for key in conn.keys("{bisheng_fs}:*"):
        conn.delete(key)


@pytest.fixture
def scheduler(redis_conn):
    return FileScheduler(connection=redis_conn)


def test_enqueue_pushes_file_and_marks_user_active(scheduler, redis_conn):
    scheduler.enqueue_file(
        user_id="42",
        file_id="100",
        preview_cache_key="pk1",
        callback_url="http://cb",
        file_ext="pdf",
    )
    assert redis_conn.lrange("{bisheng_fs}:queue:42", 0, -1) == ["100"]
    payload = redis_conn.hgetall("{bisheng_fs}:payload:100")
    assert payload["user_id"] == "42"
    assert payload["file_ext"] == "pdf"
    assert payload["preview_cache_key"] == "pk1"
    assert payload["callback_url"] == "http://cb"
    assert redis_conn.sismember("{bisheng_fs}:active_users", "42")
    assert redis_conn.sismember("{bisheng_fs}:inflight_users", "42")
    assert 0 < redis_conn.ttl("{bisheng_fs}:payload:100") <= 14400


def test_dispatch_one_respects_inflight_limit(scheduler, redis_conn):
    for fid in ("1", "2", "3"):
        scheduler.enqueue_file(user_id="9", file_id=fid, preview_cache_key="", callback_url="", file_ext="txt")
    first = scheduler.dispatch_one(user_id="9", limit=1)
    second = scheduler.dispatch_one(user_id="9", limit=1)
    assert first == "1"  # FIFO: earliest enqueued comes out first
    assert second is None  # limit reached
    assert redis_conn.smembers("{bisheng_fs}:inflight:9") == {"1"}


def test_dispatch_one_pops_when_active_users_drained(scheduler, redis_conn):
    scheduler.enqueue_file(user_id="9", file_id="1", preview_cache_key="", callback_url="", file_ext="txt")
    scheduler.dispatch_one(user_id="9", limit=5)
    # queue is empty, active_users should be cleared by the Lua script
    assert not redis_conn.sismember("{bisheng_fs}:active_users", "9")


def test_rollback_returns_file_to_queue_head(scheduler, redis_conn):
    scheduler.enqueue_file(user_id="9", file_id="1", preview_cache_key="", callback_url="", file_ext="txt")
    scheduler.enqueue_file(user_id="9", file_id="2", preview_cache_key="", callback_url="", file_ext="txt")
    dispatched = scheduler.dispatch_one(user_id="9", limit=5)
    assert dispatched == "1"
    scheduler.rollback_dispatch(user_id="9", file_id="1")
    # rollback uses RPUSH so the next RPOP picks the rolled-back file first
    assert scheduler.dispatch_one(user_id="9", limit=5) == "1"


def test_complete_clears_inflight_and_users_set_when_drained(scheduler, redis_conn):
    scheduler.enqueue_file(user_id="9", file_id="1", preview_cache_key="", callback_url="", file_ext="txt")
    scheduler.dispatch_one(user_id="9", limit=5)
    scheduler.complete_file(user_id="9", file_id="1")
    assert not redis_conn.sismember("{bisheng_fs}:inflight_users", "9")
    assert not redis_conn.smembers("{bisheng_fs}:inflight:9")


def test_complete_is_idempotent(scheduler, redis_conn):
    scheduler.enqueue_file(user_id="9", file_id="1", preview_cache_key="", callback_url="", file_ext="txt")
    scheduler.dispatch_one(user_id="9", limit=5)
    scheduler.complete_file(user_id="9", file_id="1")
    # second complete is a no-op (acks_late retry safety)
    scheduler.complete_file(user_id="9", file_id="1")
    assert not redis_conn.smembers("{bisheng_fs}:inflight:9")
```

- [ ] **Step 2: Run and confirm failure (missing `FileScheduler`)**

```bash
uv run pytest test/knowledge/test_file_scheduler_lua.py -v
```
Expected: `ImportError: cannot import name 'FileScheduler'`.

- [ ] **Step 3: Create the Lua scripts module**

Create `src/backend/bisheng/worker/knowledge/lua_scripts.py`:

```python
"""Lua scripts for the file parse scheduler.

All scripts use the literal hash tag ``{bisheng_fs}`` so that every key
they touch lands in a single Redis Cluster slot. The prefix is hard-coded
on purpose — it must not be parameterized.
"""

ENQUEUE_FILE = r"""
local prefix = '{bisheng_fs}:'
local user_id = KEYS[1]
local file_id = ARGV[1]
local preview_cache_key = ARGV[2]
local callback_url = ARGV[3]
local file_ext = ARGV[4]
local payload_ttl = tonumber(ARGV[5])

redis.call('LPUSH', prefix .. 'queue:' .. user_id, file_id)
redis.call('HSET',  prefix .. 'payload:' .. file_id,
    'preview_cache_key', preview_cache_key,
    'callback_url',      callback_url,
    'user_id',           user_id,
    'file_ext',          file_ext)
redis.call('EXPIRE', prefix .. 'payload:' .. file_id, payload_ttl)
redis.call('SADD', prefix .. 'active_users', user_id)
redis.call('SADD', prefix .. 'inflight_users', user_id)
return 1
"""

DISPATCH_ONE = r"""
local prefix = '{bisheng_fs}:'
local user_id = KEYS[1]
local limit = tonumber(ARGV[1])

local inflight_key = prefix .. 'inflight:' .. user_id
local queue_key    = prefix .. 'queue:'    .. user_id
local active_key   = prefix .. 'active_users'

if redis.call('SCARD', inflight_key) >= limit then
    return nil
end

local file_id = redis.call('RPOP', queue_key)
if not file_id then
    redis.call('SREM', active_key, user_id)
    return nil
end

if redis.call('LLEN', queue_key) == 0 then
    redis.call('SREM', active_key, user_id)
end

redis.call('SADD', inflight_key, file_id)
return file_id
"""

ROLLBACK_DISPATCH = r"""
local prefix = '{bisheng_fs}:'
local user_id = KEYS[1]
local file_id = ARGV[1]

redis.call('SREM', prefix .. 'inflight:' .. user_id, file_id)
redis.call('RPUSH', prefix .. 'queue:' .. user_id, file_id)
redis.call('SADD',  prefix .. 'active_users', user_id)
return 1
"""

COMPLETE_FILE = r"""
local prefix = '{bisheng_fs}:'
local user_id = KEYS[1]
local file_id = ARGV[1]

redis.call('SREM', prefix .. 'inflight:' .. user_id, file_id)
if redis.call('SCARD', prefix .. 'inflight:' .. user_id) == 0 then
    redis.call('SREM', prefix .. 'inflight_users', user_id)
end
return 1
"""

RELEASE_LOCK = r"""
local current = redis.call('GET', KEYS[1])
if current == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""
```

- [ ] **Step 4: Extend `scheduler.py` with `FileScheduler`**

Append to `src/backend/bisheng/worker/knowledge/scheduler.py`:

```python
import uuid
from typing import Iterable

from loguru import logger

from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.worker.knowledge.lua_scripts import (
    COMPLETE_FILE,
    DISPATCH_ONE,
    ENQUEUE_FILE,
    RELEASE_LOCK,
    ROLLBACK_DISPATCH,
)

PREFIX = "{bisheng_fs}:"
ACTIVE_USERS_KEY = f"{PREFIX}active_users"
INFLIGHT_USERS_KEY = f"{PREFIX}inflight_users"
DISPATCH_LOCK_KEY = f"{PREFIX}dispatch_lock"


def _queue_key(user_id: str) -> str:
    return f"{PREFIX}queue:{user_id}"


def _payload_key(file_id: str) -> str:
    return f"{PREFIX}payload:{file_id}"


def _inflight_key(user_id: str) -> str:
    return f"{PREFIX}inflight:{user_id}"


class FileScheduler:
    """Sync facade over the Lua scripts."""

    _PAYLOAD_TTL_SECONDS = 14400  # 4h, mirrors the Lua script's EXPIRE

    def __init__(self, connection=None):
        self._conn = connection or get_redis_client_sync().connection
        self._enqueue = self._conn.register_script(ENQUEUE_FILE)
        self._dispatch_one = self._conn.register_script(DISPATCH_ONE)
        self._rollback = self._conn.register_script(ROLLBACK_DISPATCH)
        self._complete = self._conn.register_script(COMPLETE_FILE)
        self._release_lock = self._conn.register_script(RELEASE_LOCK)

    def enqueue_file(
        self,
        *,
        user_id: str,
        file_id: str,
        preview_cache_key: str,
        callback_url: str,
        file_ext: str,
    ) -> None:
        self._enqueue(
            keys=[str(user_id)],
            args=[
                str(file_id),
                preview_cache_key or "",
                callback_url or "",
                (file_ext or "").lower(),
                self._PAYLOAD_TTL_SECONDS,
            ],
        )

    def dispatch_one(self, *, user_id: str, limit: int) -> str | None:
        result = self._dispatch_one(keys=[str(user_id)], args=[int(limit)])
        if result is None:
            return None
        return result.decode() if isinstance(result, bytes) else str(result)

    def rollback_dispatch(self, *, user_id: str, file_id: str) -> None:
        self._rollback(keys=[str(user_id)], args=[str(file_id)])

    def complete_file(self, *, user_id: str, file_id: str) -> None:
        self._complete(keys=[str(user_id)], args=[str(file_id)])

    def get_payload(self, file_id: str) -> dict[str, str]:
        raw = self._conn.hgetall(_payload_key(file_id))
        if not raw:
            return {}
        return {
            (k.decode() if isinstance(k, bytes) else k):
                (v.decode() if isinstance(v, bytes) else v)
            for k, v in raw.items()
        }

    def delete_payload(self, file_id: str) -> None:
        self._conn.delete(_payload_key(file_id))

    def active_users(self) -> list[str]:
        members = self._conn.smembers(ACTIVE_USERS_KEY)
        return [m.decode() if isinstance(m, bytes) else m for m in members]

    def inflight_users(self) -> list[str]:
        members = self._conn.smembers(INFLIGHT_USERS_KEY)
        return [m.decode() if isinstance(m, bytes) else m for m in members]

    def inflight_files(self, user_id: str) -> list[str]:
        members = self._conn.smembers(_inflight_key(user_id))
        return [m.decode() if isinstance(m, bytes) else m for m in members]

    def acquire_dispatch_lock(self, *, ttl_seconds: int) -> str | None:
        token = uuid.uuid4().hex
        if self._conn.set(DISPATCH_LOCK_KEY, token, nx=True, ex=ttl_seconds):
            return token
        return None

    def release_dispatch_lock(self, token: str) -> None:
        self._release_lock(keys=[DISPATCH_LOCK_KEY], args=[token])
```

- [ ] **Step 5: Re-run Lua tests; expect pass**

```bash
uv run pytest test/knowledge/test_file_scheduler_lua.py -v
```
Expected: 6 passed (or skipped if no local Redis — confirm at least one engineer runs them with Redis up).

- [ ] **Step 6: Format / lint / commit**

```bash
uv run ruff format bisheng/worker/knowledge/lua_scripts.py bisheng/worker/knowledge/scheduler.py test/knowledge/test_file_scheduler_lua.py
uv run ruff check --fix bisheng/worker/knowledge/lua_scripts.py bisheng/worker/knowledge/scheduler.py test/knowledge/test_file_scheduler_lua.py
git add bisheng/worker/knowledge/lua_scripts.py bisheng/worker/knowledge/scheduler.py test/knowledge/test_file_scheduler_lua.py
git commit -m "feat(scheduler): add Lua scripts + FileScheduler Redis facade"
```

---

### Task 4: `run_dispatch_round` and `trigger_dispatch_task`

**Files:**
- Modify: `src/backend/bisheng/worker/knowledge/scheduler.py` (add `run_dispatch_round` + `trigger_dispatch_task`)
- Test: `src/backend/test/knowledge/test_file_scheduler_dispatch.py` (new)

- [ ] **Step 1: Write failing tests for round-robin dispatch + rollback on apply_async failure**

Create `src/backend/test/knowledge/test_file_scheduler_dispatch.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from bisheng.worker.knowledge.scheduler import (
    FileScheduler,
    run_dispatch_round,
)


@pytest.fixture
def scheduler(tmp_path, monkeypatch):
    fake_conn = MagicMock()
    fake_conn.register_script.return_value = MagicMock()
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.get_redis_client_sync",
        lambda: MagicMock(connection=fake_conn),
    )
    return FileScheduler(connection=fake_conn)


def test_run_dispatch_round_dispatches_one_file_per_active_user(monkeypatch):
    sched = MagicMock(spec=FileScheduler)
    sched.acquire_dispatch_lock.return_value = "tok"
    sched.active_users.return_value = ["a", "b"]
    sched.dispatch_one.side_effect = ["10", "20"]
    sched.get_payload.side_effect = [
        {"preview_cache_key": "pk1", "callback_url": "cb", "file_ext": "txt"},
        {"preview_cache_key": "pk2", "callback_url": "",  "file_ext": "pdf"},
    ]
    apply_async = MagicMock()
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._parse_apply_async", apply_async
    )
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.decide_queue",
        lambda ext: "knowledge_celery",
    )
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_conf",
        lambda: MagicMock(dispatch_lock_ttl_seconds=24, limit_for=lambda _u: 1),
    )

    run_dispatch_round(scheduler=sched)

    assert apply_async.call_count == 2
    apply_async.assert_any_call(args=[10, "pk1", "cb"], queue="knowledge_celery")
    apply_async.assert_any_call(args=[20, "pk2", ""], queue="knowledge_celery")
    sched.delete_payload.assert_any_call("10")
    sched.delete_payload.assert_any_call("20")
    sched.release_dispatch_lock.assert_called_once_with("tok")


def test_run_dispatch_round_rollback_on_apply_async_failure(monkeypatch):
    sched = MagicMock(spec=FileScheduler)
    sched.acquire_dispatch_lock.return_value = "tok"
    sched.active_users.return_value = ["a"]
    sched.dispatch_one.return_value = "10"
    sched.get_payload.return_value = {
        "preview_cache_key": "pk", "callback_url": "", "file_ext": "txt",
    }
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._parse_apply_async",
        MagicMock(side_effect=RuntimeError("broker down")),
    )
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.decide_queue",
        lambda ext: "knowledge_celery",
    )
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_conf",
        lambda: MagicMock(dispatch_lock_ttl_seconds=24, limit_for=lambda _u: 1),
    )

    run_dispatch_round(scheduler=sched)

    sched.rollback_dispatch.assert_called_once_with(user_id="a", file_id="10")
    sched.delete_payload.assert_not_called()


def test_run_dispatch_round_no_lock_returns_early(monkeypatch):
    sched = MagicMock(spec=FileScheduler)
    sched.acquire_dispatch_lock.return_value = None
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_conf",
        lambda: MagicMock(dispatch_lock_ttl_seconds=24, limit_for=lambda _u: 1),
    )

    run_dispatch_round(scheduler=sched)

    sched.active_users.assert_not_called()
    sched.release_dispatch_lock.assert_not_called()


def test_run_dispatch_round_missing_payload_rolls_back(monkeypatch):
    sched = MagicMock(spec=FileScheduler)
    sched.acquire_dispatch_lock.return_value = "tok"
    sched.active_users.return_value = ["a"]
    sched.dispatch_one.return_value = "10"
    sched.get_payload.return_value = {}  # evicted
    apply_async = MagicMock()
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._parse_apply_async", apply_async
    )
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_conf",
        lambda: MagicMock(dispatch_lock_ttl_seconds=24, limit_for=lambda _u: 1),
    )

    run_dispatch_round(scheduler=sched)

    apply_async.assert_not_called()
    sched.rollback_dispatch.assert_called_once_with(user_id="a", file_id="10")
```

- [ ] **Step 2: Confirm failure**

```bash
uv run pytest test/knowledge/test_file_scheduler_dispatch.py -v
```
Expected: `ImportError: cannot import name 'run_dispatch_round'`.

- [ ] **Step 3: Implement `run_dispatch_round` + helpers + Celery task in `scheduler.py`**

Append to `scheduler.py`:

```python
from bisheng.common.services.config_service import settings as _settings
from bisheng.worker.main import bisheng_celery


def _fair_scheduler_conf():
    return _settings.knowledge_file_worker.fair_scheduler


def _fair_scheduler_enabled() -> bool:
    return bool(_settings.knowledge_file_worker.fair_scheduler_enabled)


def _parse_apply_async(*, args, queue):
    """Indirection so tests can patch without importing the celery task."""
    from bisheng.worker.knowledge.file_worker import parse_knowledge_file_celery

    parse_knowledge_file_celery.apply_async(args=args, queue=queue)


def run_dispatch_round(*, scheduler: FileScheduler | None = None) -> None:
    """Dispatch up to one file per active user in a single round."""
    conf = _fair_scheduler_conf()
    sched = scheduler or FileScheduler()

    token = sched.acquire_dispatch_lock(ttl_seconds=conf.dispatch_lock_ttl_seconds)
    if not token:
        return  # another worker already running a round
    try:
        for user_id in sched.active_users():
            limit = conf.limit_for(user_id)
            file_id = sched.dispatch_one(user_id=user_id, limit=limit)
            if file_id is None:
                continue
            payload = sched.get_payload(file_id)
            if not payload:
                sched.rollback_dispatch(user_id=user_id, file_id=file_id)
                logger.error(
                    "file_scheduler: missing payload for file_id={}; rolled back",
                    file_id,
                )
                continue
            queue = decide_queue(payload.get("file_ext", ""))
            try:
                _parse_apply_async(
                    args=[
                        int(file_id),
                        payload.get("preview_cache_key", ""),
                        payload.get("callback_url", ""),
                    ],
                    queue=queue,
                )
                sched.delete_payload(file_id)
            except Exception as exc:
                sched.rollback_dispatch(user_id=user_id, file_id=file_id)
                logger.exception(
                    "file_scheduler: dispatch failed for file_id={}; rolled back: {}",
                    file_id, exc,
                )
    finally:
        sched.release_dispatch_lock(token)


@bisheng_celery.task(name="bisheng.worker.knowledge.scheduler.trigger_dispatch_task")
def trigger_dispatch_task() -> None:
    """Event-driven trigger used after enqueue and after complete."""
    try:
        run_dispatch_round()
    except Exception:
        logger.exception("trigger_dispatch_task failed")
        raise
```

- [ ] **Step 4: Run tests, expect pass**

```bash
uv run pytest test/knowledge/test_file_scheduler_dispatch.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Format / lint / commit**

```bash
uv run ruff format bisheng/worker/knowledge/scheduler.py test/knowledge/test_file_scheduler_dispatch.py
uv run ruff check --fix bisheng/worker/knowledge/scheduler.py test/knowledge/test_file_scheduler_dispatch.py
git add bisheng/worker/knowledge/scheduler.py test/knowledge/test_file_scheduler_dispatch.py
git commit -m "feat(scheduler): implement run_dispatch_round + trigger task"
```

---

### Task 5: Public dispatch helper (`enqueue_or_dispatch`)

This is the **single entry point** for callers in `knowledge_service.py` and `knowledge_space_service.py`. It encapsulates: feature-flag check → enqueue + trigger (fair) OR direct `apply_async(queue=...)` (legacy + OCR routing).

**Files:**
- Modify: `src/backend/bisheng/worker/knowledge/scheduler.py`
- Test: `src/backend/test/knowledge/test_enqueue_or_dispatch.py` (new)

- [ ] **Step 1: Write failing test**

Create `src/backend/test/knowledge/test_enqueue_or_dispatch.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from bisheng.worker.knowledge.scheduler import enqueue_or_dispatch


def test_fair_off_uses_direct_apply_async(monkeypatch):
    apply_async = MagicMock()
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._parse_apply_async", apply_async)
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_enabled", lambda: False
    )
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.decide_queue", lambda name: "ocr_celery"
    )

    enqueue_or_dispatch(
        user_id=7,
        file_id=42,
        file_name="a.pdf",
        preview_cache_key="pk",
        callback_url="cb",
    )

    apply_async.assert_called_once_with(args=[42, "pk", "cb"], queue="ocr_celery")


def test_fair_on_calls_enqueue_and_trigger(monkeypatch):
    sched = MagicMock()
    trigger = MagicMock()
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_enabled", lambda: True
    )
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.trigger_dispatch_task",
        MagicMock(delay=trigger),
    )

    enqueue_or_dispatch(
        user_id=7,
        file_id=42,
        file_name="a.pdf",
        preview_cache_key="pk",
        callback_url="cb",
    )

    sched.enqueue_file.assert_called_once_with(
        user_id="7",
        file_id="42",
        preview_cache_key="pk",
        callback_url="cb",
        file_ext="pdf",
    )
    trigger.assert_called_once_with()


def test_fair_on_swallows_trigger_failure(monkeypatch):
    sched = MagicMock()
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_enabled", lambda: True
    )
    fake_task = MagicMock()
    fake_task.delay.side_effect = RuntimeError("broker hiccup")
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.trigger_dispatch_task", fake_task
    )

    # Should not raise — file is safely enqueued; Beat will pick it up.
    enqueue_or_dispatch(
        user_id=7, file_id=42, file_name="x.txt",
        preview_cache_key="", callback_url="",
    )
    sched.enqueue_file.assert_called_once()
```

- [ ] **Step 2: Confirm failure**

```bash
uv run pytest test/knowledge/test_enqueue_or_dispatch.py -v
```
Expected: `ImportError`.

- [ ] **Step 3: Implement helper**

Append to `scheduler.py`:

```python
def enqueue_or_dispatch(
    *,
    user_id: int,
    file_id: int,
    file_name: str,
    preview_cache_key: str | None,
    callback_url: str | None,
) -> None:
    """Single dispatch entry point used by service-layer callers."""
    preview_cache_key = preview_cache_key or ""
    callback_url = callback_url or ""

    if not _fair_scheduler_enabled():
        queue = decide_queue(file_name)
        _parse_apply_async(args=[int(file_id), preview_cache_key, callback_url], queue=queue)
        return

    scheduler = FileScheduler()
    scheduler.enqueue_file(
        user_id=str(user_id),
        file_id=str(file_id),
        preview_cache_key=preview_cache_key,
        callback_url=callback_url,
        file_ext=_extract_ext(file_name),
    )
    try:
        trigger_dispatch_task.delay()
    except Exception:
        logger.exception(
            "file_scheduler: trigger_dispatch_task.delay failed; relying on Beat fallback"
        )
```

- [ ] **Step 4: Run tests; expect pass**

```bash
uv run pytest test/knowledge/test_enqueue_or_dispatch.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Format / lint / commit**

```bash
uv run ruff format bisheng/worker/knowledge/scheduler.py test/knowledge/test_enqueue_or_dispatch.py
uv run ruff check --fix bisheng/worker/knowledge/scheduler.py test/knowledge/test_enqueue_or_dispatch.py
git add bisheng/worker/knowledge/scheduler.py test/knowledge/test_enqueue_or_dispatch.py
git commit -m "feat(scheduler): add enqueue_or_dispatch single entry point"
```

---

### Task 6: Wire `parse_knowledge_file_celery.finally` to `complete_file`

**Files:**
- Modify: `src/backend/bisheng/worker/knowledge/file_worker.py:271-289`
- Test: `src/backend/test/knowledge/test_file_worker_complete_hook.py`

- [ ] **Step 1: Write failing test**

Create `src/backend/test/knowledge/test_file_worker_complete_hook.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from bisheng.worker.knowledge import file_worker


@pytest.fixture(autouse=True)
def stub_parse(monkeypatch):
    """Stub the heavy parse to a no-op that returns a knowledge object."""
    monkeypatch.setattr(file_worker, "_parse_knowledge_file", lambda *a, **kw: MagicMock())
    yield


def test_complete_file_called_when_fair_scheduler_enabled(monkeypatch):
    monkeypatch.setattr(
        "bisheng.common.services.config_service.settings.knowledge_file_worker.fair_scheduler_enabled",
        True,
    )
    db_file = MagicMock(user_id=42)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [db_file],
    )
    complete = MagicMock()
    trigger = MagicMock()
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.FileScheduler",
        lambda: MagicMock(complete_file=complete),
    )
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.trigger_dispatch_task",
        MagicMock(delay=trigger),
    )

    file_worker.parse_knowledge_file_celery.run(100)

    complete.assert_called_once_with(user_id="42", file_id="100")
    trigger.assert_called_once_with()


def test_complete_file_skipped_when_fair_scheduler_disabled(monkeypatch):
    monkeypatch.setattr(
        "bisheng.common.services.config_service.settings.knowledge_file_worker.fair_scheduler_enabled",
        False,
    )
    db_file = MagicMock(user_id=42)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [db_file],
    )
    sched_factory = MagicMock()
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.FileScheduler", sched_factory
    )

    file_worker.parse_knowledge_file_celery.run(100)

    sched_factory.assert_not_called()


def test_complete_file_safe_when_db_row_missing(monkeypatch):
    monkeypatch.setattr(
        "bisheng.common.services.config_service.settings.knowledge_file_worker.fair_scheduler_enabled",
        True,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [],
    )
    sched_factory = MagicMock()
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.FileScheduler", sched_factory
    )

    file_worker.parse_knowledge_file_celery.run(100)  # must not raise

    sched_factory.assert_not_called()
```

- [ ] **Step 2: Confirm failure**

```bash
uv run pytest test/knowledge/test_file_worker_complete_hook.py -v
```
Expected: assertion failure (`complete_file` never called).

- [ ] **Step 3: Modify `file_worker.py`**

Replace `parse_knowledge_file_celery` (lines 271-289) with:

```python
@bisheng_celery.task(acks_late=True)
def parse_knowledge_file_celery(file_id: int, preview_cache_key: str = None, callback_url: str = None):
    """Asynchronously parse one incoming file."""
    from bisheng.common.services.config_service import settings
    from bisheng.worker.knowledge import scheduler as file_scheduler

    trace_id_var.set(f"parse_file_{file_id}")
    logger.info(
        "parse_knowledge_file_celery start preview_cache_key={}, callback_url={}",
        preview_cache_key, callback_url,
    )
    knowledge = None
    try:
        knowledge = _parse_knowledge_file(file_id, preview_cache_key, callback_url)
    except Exception as e:
        logger.error("parse_knowledge_file_celery error: {}", str(e))
    finally:
        db_file = KnowledgeFileDao.get_file_by_ids([file_id])
        if not db_file and knowledge:
            logger.debug("delete_knowledge_file_celery file_id={}", file_id)
            delete_vector_files([file_id], knowledge)

        if settings.knowledge_file_worker.fair_scheduler_enabled and db_file:
            try:
                user_id = db_file[0].user_id
                file_scheduler.FileScheduler().complete_file(
                    user_id=str(user_id), file_id=str(file_id),
                )
                file_scheduler.trigger_dispatch_task.delay()
            except Exception:
                logger.exception(
                    "file_scheduler: complete_file/trigger failed for file_id={}", file_id,
                )
```

- [ ] **Step 4: Run tests; expect pass**

```bash
uv run pytest test/knowledge/test_file_worker_complete_hook.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Format / lint / commit**

```bash
uv run ruff format bisheng/worker/knowledge/file_worker.py test/knowledge/test_file_worker_complete_hook.py
uv run ruff check --fix bisheng/worker/knowledge/file_worker.py test/knowledge/test_file_worker_complete_hook.py
git add bisheng/worker/knowledge/file_worker.py test/knowledge/test_file_worker_complete_hook.py
git commit -m "feat(scheduler): emit complete_file + trigger from parse task finally"
```

---

### Task 7: Retry task — route through scheduler when fair mode is on

**Files:**
- Modify: `src/backend/bisheng/worker/knowledge/file_worker.py:324-347`
- Test: `src/backend/test/knowledge/test_file_worker_retry.py`

- [ ] **Step 1: Write failing test**

Create `src/backend/test/knowledge/test_file_worker_retry.py`:

```python
from unittest.mock import MagicMock

import pytest

from bisheng.worker.knowledge import file_worker


def test_retry_legacy_path_still_parses_inline(monkeypatch):
    monkeypatch.setattr(
        "bisheng.common.services.config_service.settings.knowledge_file_worker.fair_scheduler_enabled",
        False,
    )
    monkeypatch.setattr(file_worker, "delete_knowledge_file_vectors", MagicMock())
    parse = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(file_worker, "_parse_knowledge_file", parse)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [MagicMock(user_id=1)],
    )

    file_worker.retry_knowledge_file_celery.run(99)

    parse.assert_called_once_with(99, None, None)


def test_retry_fair_path_reenqueues_after_cleanup(monkeypatch):
    monkeypatch.setattr(
        "bisheng.common.services.config_service.settings.knowledge_file_worker.fair_scheduler_enabled",
        True,
    )
    cleanup = MagicMock()
    monkeypatch.setattr(file_worker, "delete_knowledge_file_vectors", cleanup)
    parse = MagicMock()
    monkeypatch.setattr(file_worker, "_parse_knowledge_file", parse)

    db_row = MagicMock(user_id=11, file_name="a.pdf")
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [db_row],
    )
    status_update = MagicMock()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.update_file_status",
        status_update,
    )

    enqueue = MagicMock()
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.enqueue_or_dispatch", enqueue
    )

    file_worker.retry_knowledge_file_celery.run(99, "pk", "cb")

    cleanup.assert_called_once_with(file_ids=[99], clear_minio=False)
    parse.assert_not_called()  # parsing now happens via dispatched task
    enqueue.assert_called_once_with(
        user_id=11, file_id=99, file_name="a.pdf",
        preview_cache_key="pk", callback_url="cb",
    )


def test_retry_fair_path_cleanup_failure_marks_failed(monkeypatch):
    monkeypatch.setattr(
        "bisheng.common.services.config_service.settings.knowledge_file_worker.fair_scheduler_enabled",
        True,
    )
    monkeypatch.setattr(
        file_worker, "delete_knowledge_file_vectors",
        MagicMock(side_effect=RuntimeError("milvus down")),
    )
    status_update = MagicMock()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.update_file_status",
        status_update,
    )

    file_worker.retry_knowledge_file_celery.run(99)

    # update_file_status called with FAILED + remark
    assert status_update.called
    args, _ = status_update.call_args
    assert args[0] == [99]
```

- [ ] **Step 2: Confirm failure**

```bash
uv run pytest test/knowledge/test_file_worker_retry.py -v
```
Expected: assertion mismatch (`enqueue_or_dispatch` not called).

- [ ] **Step 3: Replace `retry_knowledge_file_celery`**

Replace lines 324-347 of `file_worker.py`:

```python
@bisheng_celery.task(acks_late=True)
def retry_knowledge_file_celery(file_id: int, preview_cache_key: str = None, callback_url: str = None):
    """Re-parse a file: clear old vectors, then either parse inline (legacy)
    or re-enqueue through the fair scheduler (when enabled).
    """
    from bisheng.common.services.config_service import settings
    from bisheng.worker.knowledge import scheduler as file_scheduler

    trace_id_var.set(f"retry_knowledge_file_{file_id}")
    logger.info("retry_knowledge_file_celery start file_id={}", file_id)

    try:
        delete_knowledge_file_vectors(file_ids=[file_id], clear_minio=False)
    except Exception as e:
        logger.exception("retry_knowledge_file_celery delete vectors error: {}", str(e))
        KnowledgeFileDao.update_file_status(
            [file_id], KnowledgeFileStatus.FAILED,
            KnowledgeFileFailedError(exception=e).to_json_str(),
        )
        return

    if settings.knowledge_file_worker.fair_scheduler_enabled:
        db_file = KnowledgeFileDao.get_file_by_ids([file_id])
        if not db_file:
            logger.warning("retry_knowledge_file_celery file_id={} disappeared", file_id)
            return
        row = db_file[0]
        KnowledgeFileDao.update_file_status([file_id], KnowledgeFileStatus.WAITING)
        file_scheduler.enqueue_or_dispatch(
            user_id=row.user_id,
            file_id=file_id,
            file_name=row.file_name,
            preview_cache_key=preview_cache_key,
            callback_url=callback_url,
        )
        return

    # Legacy path — parse inline as before.
    knowledge = None
    try:
        knowledge = _parse_knowledge_file(file_id, preview_cache_key, callback_url)
    except Exception as e:
        logger.error("retry_knowledge_file_celery error: {}", str(e))
    finally:
        db_file = KnowledgeFileDao.get_file_by_ids([file_id])
        if not db_file and knowledge:
            logger.debug("delete_knowledge_file_celery file_id={}", file_id)
            delete_vector_files([file_id], knowledge)
```

- [ ] **Step 4: Run tests; expect pass**

```bash
uv run pytest test/knowledge/test_file_worker_retry.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Format / lint / commit**

```bash
uv run ruff format bisheng/worker/knowledge/file_worker.py test/knowledge/test_file_worker_retry.py
uv run ruff check --fix bisheng/worker/knowledge/file_worker.py test/knowledge/test_file_worker_retry.py
git add bisheng/worker/knowledge/file_worker.py test/knowledge/test_file_worker_retry.py
git commit -m "feat(scheduler): retry task re-enqueues through fair scheduler"
```

---

### Task 8: Swap upload-time `.delay()` calls for `enqueue_or_dispatch`

Five call-sites identified during research:
1. `knowledge_service.py:1017` (`process_knowledge_file`)
2. `knowledge_service.py:1039` (`aprocess_knowledge_file`)
3. `knowledge_space_service.py:3043` (space upload)
4. `knowledge_utils.py:379` (`process_rebuild_file`) — already calls `retry_knowledge_file_celery`; **leave unchanged**, the retry task handles the routing.
5. `knowledge_utils.py:440` (`process_retry_files`) — same as above; leave.
6. `knowledge_space_service.py:3370` and `3386` (`batch_retry_failed_files`) — same as above; leave.

Only the three upload-time sites change in this task.

**Files:**
- Modify: `src/backend/bisheng/knowledge/domain/services/knowledge_service.py:1015-1020, 1037-1043`
- Modify: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:3042-3045`
- Test: `src/backend/test/knowledge/test_dispatch_entry_swap.py`

- [ ] **Step 1: Write failing tests**

Create `src/backend/test/knowledge/test_dispatch_entry_swap.py`:

```python
from unittest.mock import MagicMock

import pytest


def test_process_knowledge_file_uses_enqueue_or_dispatch(monkeypatch):
    """Upload entrypoint must go through scheduler.enqueue_or_dispatch."""
    from bisheng.knowledge.domain.services import knowledge_service as svc

    monkeypatch.setattr(
        svc.KnowledgeService,
        "save_knowledge_file",
        classmethod(lambda cls, *a, **kw: (MagicMock(), [], [
            MagicMock(id=1, user_id=10, file_name="a.pdf"),
            MagicMock(id=2, user_id=10, file_name="b.txt"),
        ], ["pk1", "pk2"])),
    )
    monkeypatch.setattr(
        svc.KnowledgeService, "upload_knowledge_file_hook", classmethod(lambda *a, **kw: None)
    )

    captured = []
    def fake(**kwargs):
        captured.append(kwargs)
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.enqueue_or_dispatch", fake
    )

    req = MagicMock(callback_url="cb")
    svc.KnowledgeService.process_knowledge_file(
        request=MagicMock(),
        login_user=MagicMock(user_id=10),
        background_tasks=MagicMock(),
        req_data=req,
    )

    assert len(captured) == 2
    assert captured[0]["user_id"] == 10
    assert captured[0]["file_id"] == 1
    assert captured[0]["file_name"] == "a.pdf"
    assert captured[0]["preview_cache_key"] == "pk1"
    assert captured[0]["callback_url"] == "cb"


async def test_aprocess_knowledge_file_uses_enqueue_or_dispatch(monkeypatch):
    from bisheng.knowledge.domain.services import knowledge_service as svc

    async def fake_save(cls, *a, **kw):
        return (MagicMock(), [], [MagicMock(id=5, user_id=20, file_name="img.png")], ["pk"])
    monkeypatch.setattr(svc.KnowledgeService, "asave_knowledge_file", classmethod(fake_save))
    monkeypatch.setattr(svc.KnowledgeService, "upload_knowledge_file_hook", classmethod(lambda *a, **kw: None))

    captured = []
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.enqueue_or_dispatch",
        lambda **kw: captured.append(kw),
    )

    await svc.KnowledgeService.aprocess_knowledge_file(
        request=MagicMock(),
        login_user=MagicMock(user_id=20),
        background_tasks=MagicMock(),
        req_data=MagicMock(callback_url=""),
    )

    assert captured == [
        {"user_id": 20, "file_id": 5, "file_name": "img.png",
         "preview_cache_key": "pk", "callback_url": ""},
    ]
```

- [ ] **Step 2: Confirm failure**

```bash
uv run pytest test/knowledge/test_dispatch_entry_swap.py -v
```
Expected: AssertionError — current code still calls `.delay()`.

- [ ] **Step 3: Patch `knowledge_service.py:1015-1020`**

Replace:

```python
        for index, one in enumerate(process_files):
            file_worker.parse_knowledge_file_celery.delay(one.id, preview_cache_keys[index], req_data.callback_url)
```

with:

```python
        from bisheng.worker.knowledge import scheduler as file_scheduler

        for index, one in enumerate(process_files):
            file_scheduler.enqueue_or_dispatch(
                user_id=one.user_id,
                file_id=one.id,
                file_name=one.file_name,
                preview_cache_key=preview_cache_keys[index],
                callback_url=req_data.callback_url,
            )
```

Apply the same replacement at lines 1037-1039 in `aprocess_knowledge_file`. Remove the now-unused `from bisheng.worker.knowledge import file_worker` if no other code in the function still needs it (it does for other helpers, so keep it).

- [ ] **Step 4: Patch `knowledge_space_service.py:3042-3045`**

Replace:

```python
        for index, one in enumerate(process_files):
            file_worker.parse_knowledge_file_celery.delay(
                one.id, preview_cache_keys[index]
            )
```

with:

```python
        from bisheng.worker.knowledge import scheduler as file_scheduler

        for index, one in enumerate(process_files):
            file_scheduler.enqueue_or_dispatch(
                user_id=one.user_id,
                file_id=one.id,
                file_name=one.file_name,
                preview_cache_key=preview_cache_keys[index],
                callback_url=None,
            )
```

- [ ] **Step 5: Run tests; expect pass**

```bash
uv run pytest test/knowledge/test_dispatch_entry_swap.py -v
```
Expected: 2 passed.

- [ ] **Step 6: Format / lint / commit**

```bash
uv run ruff format bisheng/knowledge/domain/services/knowledge_service.py bisheng/knowledge/domain/services/knowledge_space_service.py test/knowledge/test_dispatch_entry_swap.py
uv run ruff check --fix bisheng/knowledge/domain/services/knowledge_service.py bisheng/knowledge/domain/services/knowledge_space_service.py test/knowledge/test_dispatch_entry_swap.py
git add bisheng/knowledge/domain/services/knowledge_service.py bisheng/knowledge/domain/services/knowledge_space_service.py test/knowledge/test_dispatch_entry_swap.py
git commit -m "feat(scheduler): route upload paths through enqueue_or_dispatch"
```

---

### Task 9: Reconcile task (Cases 1–4)

**Files:**
- Modify: `src/backend/bisheng/worker/knowledge/scheduler.py` (add `reconcile_file_scheduler_task`)
- Test: `src/backend/test/knowledge/test_file_scheduler_reconcile.py`

- [ ] **Step 1: Write failing test**

Create `src/backend/test/knowledge/test_file_scheduler_reconcile.py`:

```python
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
from bisheng.worker.knowledge.scheduler import reconcile_file_scheduler_task


def _row(status, file_name="a.txt", user_id=1, update_time=None):
    m = MagicMock()
    m.status = status.value if hasattr(status, "value") else status
    m.file_name = file_name
    m.user_id = user_id
    m.update_time = update_time or datetime.utcnow()
    return m


def test_case1_done_in_db_clears_inflight(monkeypatch):
    sched = MagicMock()
    sched.inflight_users.return_value = ["7"]
    sched.inflight_files.return_value = ["100"]
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [_row(KnowledgeFileStatus.SUCCESS)],
    )

    reconcile_file_scheduler_task.run()

    sched.complete_file.assert_any_call(user_id="7", file_id="100")


def test_case2_still_waiting_reenqueues(monkeypatch):
    sched = MagicMock()
    sched.inflight_users.return_value = ["7"]
    sched.inflight_files.return_value = ["100"]
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [_row(KnowledgeFileStatus.WAITING, file_name="img.png", user_id=7)],
    )

    reconcile_file_scheduler_task.run()

    sched.complete_file.assert_any_call(user_id="7", file_id="100")
    sched.enqueue_file.assert_called_once()


def test_case3_processing_timeout_reenqueues(monkeypatch):
    sched = MagicMock()
    sched.inflight_users.return_value = ["7"]
    sched.inflight_files.return_value = ["100"]
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched
    )
    stale = datetime.utcnow() - timedelta(hours=10)
    row = _row(KnowledgeFileStatus.PROCESSING, file_name="a.pdf", user_id=7, update_time=stale)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [row],
    )
    status_update = MagicMock()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.update_file_status",
        status_update,
    )

    reconcile_file_scheduler_task.run()

    sched.complete_file.assert_called_once_with(user_id="7", file_id="100")
    sched.enqueue_file.assert_called_once()
    status_update.assert_called_once()


def test_case3_processing_fresh_skips(monkeypatch):
    sched = MagicMock()
    sched.inflight_users.return_value = ["7"]
    sched.inflight_files.return_value = ["100"]
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched
    )
    fresh = datetime.utcnow()
    row = _row(KnowledgeFileStatus.PROCESSING, update_time=fresh)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [row],
    )

    reconcile_file_scheduler_task.run()

    sched.complete_file.assert_not_called()
    sched.enqueue_file.assert_not_called()


def test_case_missing_row_clears_inflight(monkeypatch):
    sched = MagicMock()
    sched.inflight_users.return_value = ["7"]
    sched.inflight_files.return_value = ["100"]
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [],
    )

    reconcile_file_scheduler_task.run()

    sched.complete_file.assert_called_once_with(user_id="7", file_id="100")
```

- [ ] **Step 2: Confirm failure**

```bash
uv run pytest test/knowledge/test_file_scheduler_reconcile.py -v
```
Expected: `AttributeError: module ... has no attribute 'reconcile_file_scheduler_task'`.

- [ ] **Step 3: Implement reconcile task**

Append to `scheduler.py`:

```python
from datetime import datetime, timedelta

from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFileDao,
    KnowledgeFileStatus,
)


_TERMINAL_STATUSES = {
    KnowledgeFileStatus.SUCCESS.value,
    KnowledgeFileStatus.FAILED.value,
    # VIOLATION (8) may or may not exist depending on enum version — check.
}
try:
    _TERMINAL_STATUSES.add(KnowledgeFileStatus.VIOLATION.value)  # type: ignore[attr-defined]
except AttributeError:
    pass


@bisheng_celery.task(name="bisheng.worker.knowledge.scheduler.reconcile_file_scheduler_task")
def reconcile_file_scheduler_task() -> None:
    """Reconcile Redis scheduler state with the DB. Cases 1–4 from the spec."""
    conf = _fair_scheduler_conf()
    inflight_ttl = timedelta(seconds=conf.inflight_ttl_seconds)
    sched = FileScheduler()

    for user_id in sched.inflight_users():
        for file_id in sched.inflight_files(user_id):
            rows = KnowledgeFileDao.get_file_by_ids([int(file_id)])
            if not rows:
                sched.complete_file(user_id=user_id, file_id=file_id)
                logger.warning(
                    "reconcile: missing DB row, cleared inflight file_id={}", file_id
                )
                continue
            row = rows[0]
            status = row.status

            if status in _TERMINAL_STATUSES:
                sched.complete_file(user_id=user_id, file_id=file_id)
                logger.warning(
                    "reconcile: leaked inflight (status={}) cleared for file_id={}",
                    status, file_id,
                )
                continue

            if status == KnowledgeFileStatus.WAITING.value:
                # Case 2: re-enqueue
                sched.complete_file(user_id=user_id, file_id=file_id)
                sched.enqueue_file(
                    user_id=user_id, file_id=file_id,
                    preview_cache_key="", callback_url="",
                    file_ext=_extract_ext(row.file_name),
                )
                logger.error(
                    "reconcile: re-enqueued orphaned file_id={}", file_id
                )
                continue

            if status == KnowledgeFileStatus.PROCESSING.value:
                if datetime.utcnow() - row.update_time > inflight_ttl:
                    sched.complete_file(user_id=user_id, file_id=file_id)
                    KnowledgeFileDao.update_file_status(
                        [int(file_id)], KnowledgeFileStatus.WAITING,
                    )
                    sched.enqueue_file(
                        user_id=user_id, file_id=file_id,
                        preview_cache_key="", callback_url="",
                        file_ext=_extract_ext(row.file_name),
                    )
                    logger.error(
                        "reconcile: timed-out file_id={} re-enqueued", file_id
                    )

    # Case 4: drained active_users
    for user_id in sched.active_users():
        queue_empty = sched._conn.llen(_queue_key(user_id)) == 0
        inflight_empty = sched._conn.scard(_inflight_key(user_id)) == 0
        if queue_empty and inflight_empty:
            sched._conn.srem(ACTIVE_USERS_KEY, user_id)
```

- [ ] **Step 4: Run tests; expect pass**

```bash
uv run pytest test/knowledge/test_file_scheduler_reconcile.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Format / lint / commit**

```bash
uv run ruff format bisheng/worker/knowledge/scheduler.py test/knowledge/test_file_scheduler_reconcile.py
uv run ruff check --fix bisheng/worker/knowledge/scheduler.py test/knowledge/test_file_scheduler_reconcile.py
git add bisheng/worker/knowledge/scheduler.py test/knowledge/test_file_scheduler_reconcile.py
git commit -m "feat(scheduler): add reconcile_file_scheduler_task (cases 1-4)"
```

---

### Task 10: Celery wiring — Beat schedule + worker registration + queue routes

**Files:**
- Modify: `src/backend/bisheng/core/config/settings.py` (`CeleryConf.validate` — add Beat entries; `task_routers` — leave `bisheng.worker.knowledge.*` route)
- Modify: `src/backend/bisheng/worker/__init__.py` (export new tasks for autodiscovery)
- Test: `src/backend/test/knowledge/test_celery_wiring.py`

The existing routing rule `"bisheng.worker.knowledge.*": {"queue": "knowledge_celery"}` is the **default** queue. `apply_async(queue=...)` from the scheduler overrides that per-call to `ocr_celery` when needed. We do **not** change the static routing table.

- [ ] **Step 1: Write failing test**

Create `src/backend/test/knowledge/test_celery_wiring.py`:

```python
from bisheng.core.config.settings import CeleryConf


def test_beat_schedule_contains_scheduler_entries():
    conf = CeleryConf()
    assert "file_scheduler_dispatch" in conf.beat_schedule
    entry = conf.beat_schedule["file_scheduler_dispatch"]
    assert entry["task"] == "bisheng.worker.knowledge.scheduler.trigger_dispatch_task"
    # 30s default
    assert entry["schedule"] == 30.0

    assert "file_scheduler_reconcile" in conf.beat_schedule
    rentry = conf.beat_schedule["file_scheduler_reconcile"]
    assert rentry["task"] == "bisheng.worker.knowledge.scheduler.reconcile_file_scheduler_task"
    assert rentry["schedule"] == 300.0


def test_worker_init_exports_scheduler_tasks():
    from bisheng import worker

    assert hasattr(worker, "trigger_dispatch_task")
    assert hasattr(worker, "reconcile_file_scheduler_task")
```

- [ ] **Step 2: Confirm failure**

```bash
uv run pytest test/knowledge/test_celery_wiring.py -v
```
Expected: KeyError / AttributeError.

- [ ] **Step 3: Add Beat entries in `CeleryConf.validate`**

In `src/backend/bisheng/core/config/settings.py`, inside `CeleryConf.validate`, append (before the `for key, task_info in self.beat_schedule.items()` conversion block):

```python
        if 'file_scheduler_dispatch' not in self.beat_schedule:
            self.beat_schedule['file_scheduler_dispatch'] = {
                'task': 'bisheng.worker.knowledge.scheduler.trigger_dispatch_task',
                'schedule': 30.0,
            }
        if 'file_scheduler_reconcile' not in self.beat_schedule:
            self.beat_schedule['file_scheduler_reconcile'] = {
                'task': 'bisheng.worker.knowledge.scheduler.reconcile_file_scheduler_task',
                'schedule': 300.0,
            }
```

- [ ] **Step 4: Export tasks in `worker/__init__.py`**

Open `src/backend/bisheng/worker/__init__.py` and append:

```python
from bisheng.worker.knowledge.scheduler import (
    reconcile_file_scheduler_task,
    trigger_dispatch_task,
)
```

- [ ] **Step 5: Run tests; expect pass**

```bash
uv run pytest test/knowledge/test_celery_wiring.py -v
```
Expected: 2 passed.

- [ ] **Step 6: Format / lint / commit**

```bash
uv run ruff format bisheng/core/config/settings.py bisheng/worker/__init__.py test/knowledge/test_celery_wiring.py
uv run ruff check --fix bisheng/core/config/settings.py bisheng/worker/__init__.py test/knowledge/test_celery_wiring.py
git add bisheng/core/config/settings.py bisheng/worker/__init__.py test/knowledge/test_celery_wiring.py
git commit -m "feat(scheduler): register Beat entries + export tasks"
```

---

### Task 11: Worker startup modes (`BISHENG_CELERY_MODE`)

**Files:**
- Modify: `src/backend/bisheng/run_celery.py`
- Test: `src/backend/test/knowledge/test_run_celery_modes.py`

- [ ] **Step 1: Write failing test**

Create `src/backend/test/knowledge/test_run_celery_modes.py`:

```python
import os
from unittest.mock import MagicMock

import pytest


def test_default_mode_listens_all_queues(monkeypatch):
    from bisheng import run_celery as r

    captured = []
    monkeypatch.setattr(r.bisheng_celery, "start", lambda argv: captured.append(argv))
    monkeypatch.delenv("BISHENG_CELERY_MODE", raising=False)
    monkeypatch.delenv("BISHENG_CELERY_CONCURRENCY", raising=False)

    r.main()

    assert captured == [[
        "worker", "-l", "info", "-c", "20", "-P", "threads",
        "-Q", "ocr_celery,knowledge_celery,workflow_celery,celery",
    ]]


def test_ocr_mode_listens_ocr_queue_only(monkeypatch):
    from bisheng import run_celery as r
    captured = []
    monkeypatch.setattr(r.bisheng_celery, "start", lambda argv: captured.append(argv))
    monkeypatch.setenv("BISHENG_CELERY_MODE", "ocr")
    monkeypatch.setenv("BISHENG_CELERY_CONCURRENCY", "5")

    r.main()

    assert captured == [[
        "worker", "-l", "info", "-c", "5", "-P", "threads",
        "-Q", "ocr_celery",
    ]]


def test_file_mode_excludes_ocr_queue(monkeypatch):
    from bisheng import run_celery as r
    captured = []
    monkeypatch.setattr(r.bisheng_celery, "start", lambda argv: captured.append(argv))
    monkeypatch.setenv("BISHENG_CELERY_MODE", "file")
    monkeypatch.setenv("BISHENG_CELERY_CONCURRENCY", "15")

    r.main()

    assert captured == [[
        "worker", "-l", "info", "-c", "15", "-P", "threads",
        "-Q", "knowledge_celery,workflow_celery,celery",
    ]]


def test_invalid_mode_raises(monkeypatch):
    from bisheng import run_celery as r
    monkeypatch.setenv("BISHENG_CELERY_MODE", "bogus")
    with pytest.raises(ValueError):
        r.main()
```

- [ ] **Step 2: Confirm failure**

```bash
uv run pytest test/knowledge/test_run_celery_modes.py -v
```
Expected: AttributeError (no `main()`).

- [ ] **Step 3: Rewrite `run_celery.py`**

Replace the file content:

```python
import os

from bisheng.worker.main import bisheng_celery

_QUEUES = {
    "all": "ocr_celery,knowledge_celery,workflow_celery,celery",
    "ocr": "ocr_celery",
    "file": "knowledge_celery,workflow_celery,celery",
}


def main() -> None:
    mode = os.environ.get("BISHENG_CELERY_MODE", "all")
    if mode not in _QUEUES:
        raise ValueError(
            f"BISHENG_CELERY_MODE={mode!r} is invalid; expected one of {sorted(_QUEUES)}"
        )
    concurrency = os.environ.get("BISHENG_CELERY_CONCURRENCY", "20")
    bisheng_celery.start(argv=[
        "worker", "-l", "info", "-c", concurrency, "-P", "threads",
        "-Q", _QUEUES[mode],
    ])


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests; expect pass**

```bash
uv run pytest test/knowledge/test_run_celery_modes.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Format / lint / commit**

```bash
uv run ruff format bisheng/run_celery.py test/knowledge/test_run_celery_modes.py
uv run ruff check --fix bisheng/run_celery.py test/knowledge/test_run_celery_modes.py
git add bisheng/run_celery.py test/knowledge/test_run_celery_modes.py
git commit -m "feat(scheduler): BISHENG_CELERY_MODE worker selector"
```

---

### Task 12: End-to-end smoke test (real Redis required)

**Files:**
- Test: `src/backend/test/knowledge/test_file_scheduler_e2e.py`

This test is the safety net that catches integration mistakes the unit tests miss. It exercises: enqueue → trigger → apply_async called with the right queue → mocked celery task simulates completion → next file in the same user's queue is dispatched.

- [ ] **Step 1: Write the e2e test**

```python
import socket
from unittest.mock import MagicMock

import pytest
import redis

from bisheng.worker.knowledge import scheduler as s


def _redis_reachable():
    try:
        with socket.create_connection(("localhost", 6379), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _redis_reachable(), reason="needs Redis")


@pytest.fixture
def redis_conn():
    conn = redis.StrictRedis(host="localhost", port=6379, db=15, decode_responses=True)
    for k in conn.keys("{bisheng_fs}:*"):
        conn.delete(k)
    yield conn
    for k in conn.keys("{bisheng_fs}:*"):
        conn.delete(k)


def test_round_trip_two_files_one_user(redis_conn, monkeypatch):
    monkeypatch.setattr(s, "get_redis_client_sync", lambda: MagicMock(connection=redis_conn))
    apply_async = MagicMock()
    monkeypatch.setattr(s, "_parse_apply_async", apply_async)
    monkeypatch.setattr(s, "decide_queue", lambda name: "knowledge_celery")
    monkeypatch.setattr(s, "_fair_scheduler_enabled", lambda: True)
    monkeypatch.setattr(
        s, "_fair_scheduler_conf",
        lambda: MagicMock(dispatch_lock_ttl_seconds=24, limit_for=lambda _: 1),
    )

    s.enqueue_or_dispatch(
        user_id=7, file_id=100, file_name="a.txt",
        preview_cache_key="pk1", callback_url="",
    )
    s.enqueue_or_dispatch(
        user_id=7, file_id=101, file_name="b.txt",
        preview_cache_key="pk2", callback_url="",
    )
    # The `delay()` from enqueue_or_dispatch is itself a celery task; we
    # invoke run_dispatch_round directly to simulate the trigger.
    s.run_dispatch_round()

    # Only one dispatched per round because limit_for == 1
    assert apply_async.call_count == 1
    apply_async.assert_called_with(args=[100, "pk1", ""], queue="knowledge_celery")

    # Simulate task completion
    sched = s.FileScheduler(connection=redis_conn)
    sched.complete_file(user_id="7", file_id="100")
    s.run_dispatch_round()

    assert apply_async.call_count == 2
    apply_async.assert_called_with(args=[101, "pk2", ""], queue="knowledge_celery")


def test_round_robin_across_two_users(redis_conn, monkeypatch):
    monkeypatch.setattr(s, "get_redis_client_sync", lambda: MagicMock(connection=redis_conn))
    apply_async = MagicMock()
    monkeypatch.setattr(s, "_parse_apply_async", apply_async)
    monkeypatch.setattr(s, "decide_queue", lambda name: "knowledge_celery")
    monkeypatch.setattr(s, "_fair_scheduler_enabled", lambda: True)
    monkeypatch.setattr(
        s, "_fair_scheduler_conf",
        lambda: MagicMock(dispatch_lock_ttl_seconds=24, limit_for=lambda _: 1),
    )

    for fid in (1, 2):
        s.enqueue_or_dispatch(
            user_id=1, file_id=fid, file_name="x.txt",
            preview_cache_key="", callback_url="",
        )
    s.enqueue_or_dispatch(
        user_id=2, file_id=99, file_name="x.txt",
        preview_cache_key="", callback_url="",
    )

    s.run_dispatch_round()
    # One file per user => 2 dispatches in this round, not 3.
    assert apply_async.call_count == 2
    queued_file_ids = sorted(call.kwargs.get("args", call.args[0])[0] for call in apply_async.call_args_list)
    assert queued_file_ids == [1, 99]
```

- [ ] **Step 2: Run e2e**

```bash
uv run pytest test/knowledge/test_file_scheduler_e2e.py -v
```
Expected: 2 passed (or skipped if Redis unreachable).

- [ ] **Step 3: Format / lint / commit**

```bash
uv run ruff format test/knowledge/test_file_scheduler_e2e.py
uv run ruff check --fix test/knowledge/test_file_scheduler_e2e.py
git add test/knowledge/test_file_scheduler_e2e.py
git commit -m "test(scheduler): e2e round-trip + per-user round-robin"
```

---

### Task 13: Full suite sanity + dual-DB arch-guard check

- [ ] **Step 1: Run full knowledge test directory**

```bash
uv run pytest test/knowledge/ -q
```
Expected: all green; no regressions in existing tests.

- [ ] **Step 2: Run arch-guard on touched files**

```bash
bash scripts/arch-guard.sh bisheng/worker/knowledge/scheduler.py bisheng/worker/knowledge/file_worker.py bisheng/knowledge/domain/services/knowledge_service.py bisheng/knowledge/domain/services/knowledge_space_service.py bisheng/core/config/settings.py
```
Expected: no VIOLATION lines. The `scheduler.py` import of `KnowledgeFileDao` is in the worker layer (allowed). If RULE-3 WARNING appears for `knowledge_service.py` because of the existing `database/models` import, that's pre-existing and out of scope.

- [ ] **Step 3: DM8 dialect check**

This change touches no SQL — all new state is in Redis. Confirm by:

```bash
grep -n "raw\|execute\|JSON_EXTRACT\|information_schema" bisheng/worker/knowledge/scheduler.py
```
Expected: no matches.

- [ ] **Step 4: Smoke run an OCR-mode worker locally (manual)**

```bash
bash docker/local-dev/start-middleware.sh    # ensure Redis is up
export config=config.yaml
BISHENG_CELERY_MODE=ocr BISHENG_CELERY_CONCURRENCY=2 uv run python bisheng/run_celery.py
# In a second terminal:
BISHENG_CELERY_MODE=file BISHENG_CELERY_CONCURRENCY=4 uv run python bisheng/run_celery.py
# In a third terminal:
uv run celery -A bisheng.worker.main beat -l info
```

Confirm in logs:
- Beat fires `file_scheduler_dispatch` every 30s.
- Beat fires `file_scheduler_reconcile` every 5 min.
- Workers register only the queues they're scoped to.

- [ ] **Step 5: Final commit if any post-fix tweaks**

```bash
git status
# commit only if anything changed during the smoke verification
```

---

## Migration / rollout notes (carry into the PR description)

1. **Phase 1 — OCR queue only**: ship with `ocr_queue_enabled=true`, `fair_scheduler_enabled=false`. Deploy two worker pools (`BISHENG_CELERY_MODE=ocr` and `=file`). Validate concurrency isolation.
2. **Phase 2 — fair scheduler**: flip `fair_scheduler_enabled=true` with `max_per_user_inflight=3`. Watch `{bisheng_fs}:queue:*` length metrics; tune down to 1 once stable.
3. **Rollback**: flip either flag back to `false`. Beat + reconcile drain any in-flight Redis state on their next tick. The legacy `parse_knowledge_file_celery.delay()` path is fully preserved by `enqueue_or_dispatch` when both flags are off.

## Manual operational items

- Document the new `BISHENG_CELERY_MODE` env var in the deployment runbook.
- Add Redis monitoring alerts on `{bisheng_fs}:queue:*` length (e.g. > 1000 per user is suspicious — see spec §6.6).
- The Beat fallback (30s) is the safety net if `trigger_dispatch_task.delay()` ever fails; do not lower the interval below the lock TTL.
