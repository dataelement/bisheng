"""File parse scheduler — OCR routing helpers and (later tasks) fair dispatch."""

from __future__ import annotations

import threading
import uuid

from loguru import logger

from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    get_current_tenant_id,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFileDao,
    KnowledgeFileStatus,
)
from bisheng.worker.knowledge.lua_scripts import (
    COMPLETE_FILE,
    CONFIRM_DISPATCH,
    DISPATCH_ONE,
    DROP_DISPATCH,
    ENQUEUE_FILE,
    REFRESH_LOCK,
    RELEASE_LOCK,
    ROLLBACK_DISPATCH,
)
from bisheng.worker.main import bisheng_celery

KNOWLEDGE_QUEUE = "knowledge_celery"
_IMAGE_EXTS = frozenset({"png", "jpg", "jpeg", "bmp"})


def _ocr_queue_enabled() -> bool:
    return bool(settings.knowledge_file_worker.ocr_queue_enabled)


def _loader_configured() -> bool:
    """True when the active OCR loader has a URL configured.

    Delegates to ``KnowledgeConf.image_parser_enabled`` so we share one
    source of truth with the actual parse pipeline in
    ``bisheng/knowledge/rag/base_file_pipeline.py``.
    """
    try:
        return bool(settings.get_knowledge().image_parser_enabled)
    except Exception:
        logger.exception("file_scheduler: failed to load KnowledgeConf; treating as no OCR")
        return False


def _extract_ext(file_name: str) -> str:
    _, dot, ext = file_name.rpartition(".")
    if not dot:
        return ""
    return ext.lower()


def needs_ocr_queue(file_ext_or_name: str) -> bool:
    raw = (file_ext_or_name or "").lower()
    ext = _extract_ext(raw) if "." in raw else raw
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


# ---------------------------------------------------------------------------
# Redis key constants (all share the {bisheng_fs} hash tag for cluster slot
# consistency — must not be changed without updating the Lua scripts too)
# ---------------------------------------------------------------------------

PREFIX = "{bisheng_fs}:"
ACTIVE_USERS_KEY = f"{PREFIX}active_users"
INFLIGHT_USERS_KEY = f"{PREFIX}inflight_users"
INFLIGHT_QUEUE_KEY = f"{PREFIX}inflight_queue"
DISPATCH_LOCK_KEY = f"{PREFIX}dispatch_lock"


def _queue_key(user_id: str) -> str:
    return f"{PREFIX}queue:{user_id}"


def _payload_key(file_id: str) -> str:
    return f"{PREFIX}payload:{file_id}"


def _inflight_key(user_id: str) -> str:
    return f"{PREFIX}inflight:{user_id}"


def _inflight_total_key(queue: str) -> str:
    return f"{PREFIX}inflight_total:{queue}"


def _parse_lock_key(file_id: str) -> str:
    return f"{PREFIX}parse_lock:{file_id}"


class FileScheduler:
    """Sync facade over the Lua scripts for fair-dispatch file scheduling."""

    # Fallback payload TTL when a caller doesn't pass one (e.g. low-level tests).
    # Production callers thread ``FairSchedulerConf.payload_ttl_seconds`` through.
    # Kept long on purpose: payload is the dispatch context and must outlive the
    # file's stay in the FIFO (see settings.payload_ttl_seconds rationale).
    _PAYLOAD_TTL_SECONDS = 604800  # 7 d

    def __init__(self, connection=None):
        if connection is not None:
            self._conn = connection
        else:
            # Lazy import keeps top-level import of scheduler.py cheap in tests
            # that don't need a real Redis connection.
            from bisheng.core.cache.redis_manager import get_redis_client_sync

            self._conn = get_redis_client_sync().connection
        self._enqueue = self._conn.register_script(ENQUEUE_FILE)
        self._dispatch_one = self._conn.register_script(DISPATCH_ONE)
        self._confirm = self._conn.register_script(CONFIRM_DISPATCH)
        self._rollback = self._conn.register_script(ROLLBACK_DISPATCH)
        self._drop = self._conn.register_script(DROP_DISPATCH)
        self._complete = self._conn.register_script(COMPLETE_FILE)
        self._release_lock_script = self._conn.register_script(RELEASE_LOCK)
        self._refresh_lock_script = self._conn.register_script(REFRESH_LOCK)

    def enqueue_file(
        self,
        *,
        user_id: str,
        file_id: str,
        preview_cache_key: str,
        callback_url: str,
        file_ext: str,
        tenant_id: int | str | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        self._enqueue(
            keys=[str(user_id)],
            args=[
                str(file_id),
                preview_cache_key or "",
                callback_url or "",
                (file_ext or "").lower(),
                ttl_seconds or self._PAYLOAD_TTL_SECONDS,
                "" if tenant_id is None else str(tenant_id),
            ],
        )

    def dispatch_one(self, *, user_id: str) -> str | None:
        result = self._dispatch_one(keys=[str(user_id)])
        if result is None:
            return None
        return result.decode() if isinstance(result, bytes) else str(result)

    def confirm_dispatch(self, *, file_id: str, queue: str) -> None:
        """Confirm a successful dispatch: record queue, bump the queue's global
        in-flight counter, drop the payload. Called only after apply_async OK."""
        self._confirm(keys=[str(file_id)], args=[str(queue)])

    def inflight_count(self, *, user_id: str) -> int:
        return int(self._conn.scard(_inflight_key(user_id)))

    def inflight_total(self, *, queue: str) -> int:
        raw = self._conn.get(_inflight_total_key(queue))
        return int(raw) if raw else 0

    def recompute_inflight_totals(self, *, queues: list[str]) -> None:
        """Authoritatively rebuild every queue's in-flight counter from the
        ``inflight_queue`` map. Self-heals counter drift caused by lost
        confirm/complete callbacks (reconcile safety net)."""
        raw = self._conn.hgetall(INFLIGHT_QUEUE_KEY)
        counts: dict[str, int] = {}
        for _fid, q in (raw or {}).items():
            q = q.decode() if isinstance(q, bytes) else q
            counts[q] = counts.get(q, 0) + 1
        for q in set(queues) | set(counts):
            self._conn.set(_inflight_total_key(q), counts.get(q, 0))

    def rollback_dispatch(self, *, user_id: str, file_id: str) -> None:
        self._rollback(keys=[str(user_id)], args=[str(file_id)])

    def drop_inflight(self, *, user_id: str, file_id: str) -> None:
        """Discard a ghost in-flight entry without re-queuing it.

        Used when a popped file cannot be parsed (payload lost AND the DB row is
        terminal or gone). Unlike ``rollback_dispatch`` it does NOT push the file
        back to the queue — re-queuing a dead entry is what makes it a poison
        pill that blocks everything behind it.
        """
        self._drop(keys=[str(user_id)], args=[str(file_id)])

    def put_payload(
        self,
        *,
        file_id: str,
        preview_cache_key: str,
        callback_url: str,
        user_id: str,
        file_ext: str,
        tenant_id: int | str | None,
        ttl_seconds: int,
    ) -> None:
        """(Re)write a file's payload hash with a fresh TTL.

        Used to rebuild dispatch context for a still-WAITING file whose payload
        expired while queued. Safe as plain Redis calls: callers hold the
        dispatch lock (or run in reconcile), so there is no competing writer.
        """
        key = _payload_key(file_id)
        self._conn.hset(
            key,
            mapping={
                "preview_cache_key": preview_cache_key or "",
                "callback_url": callback_url or "",
                "user_id": str(user_id),
                "file_ext": (file_ext or "").lower(),
                "tenant_id": "" if tenant_id is None else str(tenant_id),
            },
        )
        self._conn.expire(key, ttl_seconds)

    def queued_files(self, *, user_id: str) -> list[str]:
        members = self._conn.lrange(_queue_key(user_id), 0, -1)
        return [m.decode() if isinstance(m, bytes) else m for m in members]

    def remove_from_queue(self, *, user_id: str, file_id: str) -> None:
        """Remove every occurrence of a file id from a user's FIFO queue."""
        self._conn.lrem(_queue_key(user_id), 0, str(file_id))

    def complete_file(self, *, user_id: str, file_id: str) -> None:
        self._complete(keys=[str(user_id)], args=[str(file_id)])

    def release_file(self, *, file_id: str) -> bool:
        """Release a file's in-flight slot from whichever user holds it.

        Safety net for when the file's DB row is gone (deleted) or invisible
        under the current tenant context: without this, a lost completion
        leaks the in-flight slot — the user keeps a phantom in-flight entry and
        the queue's global concurrency counter never gets its slot back.
        Returns True if a slot was released.
        """
        target = str(file_id)
        for uid in self.inflight_users():
            if target in self.inflight_files(user_id=uid):
                self.complete_file(user_id=uid, file_id=target)
                return True
        return False

    def purge_file(self, *, user_id: str, file_id: str) -> None:
        """Remove a file from the scheduler entirely (queue + inflight + payload).

        Called when a file is deleted so it does not linger as a ghost entry
        that later gets dispatched against a non-existent DB row.
        """
        uid = str(user_id)
        fid = str(file_id)
        self._conn.lrem(_queue_key(uid), 0, fid)
        self._conn.srem(_inflight_key(uid), fid)
        self._conn.delete(_payload_key(fid))
        # If the file was already confirmed in-flight, return its slot to the
        # queue counter so deleting a parsing file doesn't leak capacity.
        q = self._conn.hget(INFLIGHT_QUEUE_KEY, fid)
        if q:
            q = q.decode() if isinstance(q, bytes) else q
            self._conn.decr(_inflight_total_key(q))
            self._conn.hdel(INFLIGHT_QUEUE_KEY, fid)
        if self._conn.scard(_inflight_key(uid)) == 0:
            self._conn.srem(INFLIGHT_USERS_KEY, uid)
        if self._conn.llen(_queue_key(uid)) == 0:
            self._conn.srem(ACTIVE_USERS_KEY, uid)

    def get_payload(self, *, file_id: str) -> dict[str, str]:
        raw = self._conn.hgetall(_payload_key(file_id))
        if not raw:
            return {}
        return {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in raw.items()
        }

    def active_users(self) -> list[str]:
        members = self._conn.smembers(ACTIVE_USERS_KEY)
        return [m.decode() if isinstance(m, bytes) else m for m in members]

    def inflight_users(self) -> list[str]:
        members = self._conn.smembers(INFLIGHT_USERS_KEY)
        return [m.decode() if isinstance(m, bytes) else m for m in members]

    def inflight_files(self, *, user_id: str) -> list[str]:
        members = self._conn.smembers(_inflight_key(user_id))
        return [m.decode() if isinstance(m, bytes) else m for m in members]

    def acquire_dispatch_lock(self, *, ttl_seconds: int) -> str | None:
        token = uuid.uuid4().hex
        if self._conn.set(DISPATCH_LOCK_KEY, token, nx=True, ex=ttl_seconds):
            return token
        return None

    def release_dispatch_lock(self, token: str) -> None:
        self._release_lock_script(keys=[DISPATCH_LOCK_KEY], args=[token])

    # -- Per-file parse lock ------------------------------------------------
    # Guarantees a single concurrent parse per file. The dispatch path's
    # in-flight set can't enforce this because duplicate parse tasks also reach
    # the worker OUT of band: acks_late broker redelivery after an OOM kill, and
    # reconcile re-enqueue of a file that is still parsing. The parse task itself
    # must therefore hold this lock for its whole run.

    def acquire_parse_lock(self, *, file_id: str, ttl_seconds: int) -> str | None:
        """Try to claim the parse slot for ``file_id``. Returns a token on
        success, or ``None`` when another worker already holds it (caller must
        then skip parsing — it's a duplicate)."""
        token = uuid.uuid4().hex
        if self._conn.set(_parse_lock_key(file_id), token, nx=True, ex=ttl_seconds):
            return token
        return None

    def refresh_parse_lock(self, *, file_id: str, token: str, ttl_seconds: int) -> bool:
        """Extend the lock TTL, but only if this worker still owns it. Returns
        True if refreshed, False if the lock is gone or now held by someone else."""
        result = self._refresh_lock_script(keys=[_parse_lock_key(file_id)], args=[token, ttl_seconds])
        return bool(result)

    def release_parse_lock(self, *, file_id: str, token: str) -> None:
        """Release the parse lock, but only if this worker still owns it (a stale
        token must not delete a lock a later worker re-acquired)."""
        self._release_lock_script(keys=[_parse_lock_key(file_id)], args=[token])

    def parse_lock_alive(self, *, file_id: str) -> bool:
        """True while some worker is actively parsing ``file_id`` (heartbeat keeps
        the lock present). Reconcile uses this to tell a long-but-healthy parse
        apart from a dead worker."""
        return bool(self._conn.exists(_parse_lock_key(file_id)))


# ---------------------------------------------------------------------------
# Fair-dispatch helpers and Celery trigger task
# ---------------------------------------------------------------------------


def _fair_scheduler_conf():
    return settings.knowledge_file_worker.fair_scheduler


def _fair_scheduler_enabled() -> bool:
    return bool(settings.knowledge_file_worker.fair_scheduler_enabled)


def _parse_apply_async(*, args, queue):
    """Indirection so tests can patch without importing the celery task."""
    from bisheng.worker.knowledge.file_worker import parse_knowledge_file_celery

    parse_knowledge_file_celery.apply_async(args=args, queue=queue)


def start_parse_heartbeat(scheduler: FileScheduler, *, file_id: str, token: str, conf) -> callable:
    """Keep a parse lock alive for the whole (possibly multi-hour) parse.

    Spawns a daemon thread that re-EXPIREs ``parse_lock:<file_id>`` every
    ~ttl/3 until stopped. Returns a stopper callable to invoke in the parse
    task's ``finally``. Best-effort: if the worker dies the thread dies with it
    and the lock self-clears within one TTL, letting reconcile recover the file.
    """
    ttl = int(conf.parse_lock_ttl_seconds)
    interval = max(5, ttl // 3)
    stop = threading.Event()

    def _beat() -> None:
        # wait-first: the lock already has a full TTL from acquire, so refresh
        # only when it's about to age, and exit promptly once stopped.
        while not stop.wait(interval):
            try:
                scheduler.refresh_parse_lock(file_id=file_id, token=token, ttl_seconds=ttl)
            except Exception:
                logger.exception("parse heartbeat refresh failed for file_id={}", file_id)

    thread = threading.Thread(target=_beat, name=f"parse-hb-{file_id}", daemon=True)
    thread.start()

    def _stop() -> None:
        stop.set()
        thread.join(timeout=2)

    return _stop


def _recover_payload(
    scheduler: FileScheduler,
    conf,
    *,
    user_id: str,
    file_id: str,
) -> dict[str, str] | None:
    """Recover a popped file whose payload is gone.

    Returns a rebuilt payload dict if the file is still WAITING (caller should
    dispatch it), or ``None`` if it is a ghost that must not be parsed (terminal
    DB status or deleted row) — in which case the entry is discarded here.

    Beat-driven rounds run under the default tenant, but the file can belong to
    any tenant, so the DB lookup bypasses the auto-injected tenant filter.
    """
    with bypass_tenant_filter():
        rows = KnowledgeFileDao.get_file_by_ids([int(file_id)])
    if not rows or rows[0].status != KnowledgeFileStatus.WAITING.value:
        # Ghost: success/failed/timeout/violation, mid-flight elsewhere, or the
        # row is gone. Discard it WITHOUT re-queuing so it can't block the queue.
        scheduler.drop_inflight(user_id=user_id, file_id=file_id)
        status = rows[0].status if rows else None
        logger.warning(
            "file_scheduler: discarded ghost file_id={} (db_status={})",
            file_id,
            status,
        )
        return None

    row = rows[0]
    payload = {
        "preview_cache_key": "",
        "callback_url": "",
        "user_id": str(user_id),
        "file_ext": _extract_ext(row.file_name),
        "tenant_id": "" if getattr(row, "tenant_id", None) is None else str(row.tenant_id),
    }
    scheduler.put_payload(
        file_id=file_id,
        ttl_seconds=conf.payload_ttl_seconds,
        **payload,
    )
    logger.warning(
        "file_scheduler: rebuilt expired payload for WAITING file_id={}",
        file_id,
    )
    return payload


def run_dispatch_round(*, scheduler: FileScheduler | None = None) -> None:
    """Fill each queue up to its global concurrency cap, fairly.

    Algorithm — weighted least-in-flight backfill (see design spec §7):
    repeatedly pick the active user with the smallest ``in_flight / weight``
    and dispatch one of its files, until every target queue is at capacity or
    no user has a dispatchable file left. There is NO per-user in-flight
    ceiling; fairness comes from always serving the user currently holding the
    fewest slots, so a freed slot goes to whoever is most starved (not to the
    user with the longest queue).
    """
    conf = _fair_scheduler_conf()
    sched = scheduler if scheduler is not None else FileScheduler()

    token = sched.acquire_dispatch_lock(ttl_seconds=conf.dispatch_lock_ttl_seconds)
    if not token:
        return  # another worker already running a round
    try:
        users = sched.active_users()
        if not users:
            return

        # Current in-flight share per user (local snapshot, bumped as we go).
        share = {u: sched.inflight_count(user_id=u) for u in users}
        cap: dict[str, int] = {}
        inflight: dict[str, int] = {}
        saturated: set[str] = set()
        skipped: set[str] = set()

        def _queue_state(q: str) -> tuple[int, int]:
            if q not in cap:
                cap[q] = conf.concurrency_for(q)
                inflight[q] = sched.inflight_total(queue=q)
            return cap[q], inflight[q]

        while True:
            eligible = [u for u in users if u not in skipped]
            if not eligible:
                break
            user_id = min(eligible, key=lambda u: share[u] / conf.weight_for(u))

            file_id = sched.dispatch_one(user_id=user_id)
            if file_id is None:
                skipped.add(user_id)  # user's queue is empty
                continue

            payload = sched.get_payload(file_id=file_id)
            if not payload:
                # The payload expired (TTL) or was removed while the id lingered in
                # the FIFO. Self-heal instead of re-queuing-as-is: a payload-less
                # file pushed back to the tail is a poison pill that blocks the
                # whole queue (head-of-line blocking). Rebuild it from the DB if
                # the file still needs parsing, otherwise discard the ghost. Either
                # way DON'T skip the user — keep draining the round.
                payload = _recover_payload(sched, conf, user_id=user_id, file_id=file_id)
                if payload is None:
                    continue

            queue = decide_queue(payload.get("file_ext", ""))
            q_cap, q_inflight = _queue_state(queue)
            if queue in saturated or q_inflight >= q_cap:
                # Target queue is full. The user's FIFO head is stuck behind it,
                # so put the file back and skip this user for the round (avoids
                # repeatedly popping/rolling back the same file).
                saturated.add(queue)
                sched.rollback_dispatch(user_id=user_id, file_id=file_id)
                skipped.add(user_id)
                continue

            # Stamp the parse task with the file's OWNING tenant (captured at
            # enqueue time), not the tenant driving this round. Beat-driven
            # rounds run under the default tenant; without this a cross-tenant
            # file would be parsed under the wrong context and never found.
            payload_tenant = payload.get("tenant_id") or ""
            tenant_token = current_tenant_id.set(int(payload_tenant)) if payload_tenant else None
            try:
                _parse_apply_async(
                    args=[
                        int(file_id),
                        payload.get("preview_cache_key", ""),
                        payload.get("callback_url", ""),
                    ],
                    queue=queue,
                )
            except Exception as exc:
                sched.rollback_dispatch(user_id=user_id, file_id=file_id)
                logger.exception(
                    "file_scheduler: dispatch failed for file_id={}; rolled back: {}",
                    file_id,
                    exc,
                )
                skipped.add(user_id)
                continue
            finally:
                if tenant_token is not None:
                    current_tenant_id.reset(tenant_token)

            # apply_async succeeded → confirm (record queue + INCR counter + drop payload)
            sched.confirm_dispatch(file_id=file_id, queue=queue)
            inflight[queue] += 1
            share[user_id] += 1
    finally:
        sched.release_dispatch_lock(token)


@bisheng_celery.task(
    name="bisheng.worker.knowledge.scheduler.trigger_dispatch_task",
    acks_late=True,
)
def trigger_dispatch_task() -> None:
    """Event-driven trigger called after enqueue and after complete."""
    if not _fair_scheduler_enabled():
        return
    try:
        run_dispatch_round()
    except Exception:
        logger.exception("trigger_dispatch_task failed")
        raise


def enqueue_or_dispatch(
    *,
    user_id: int,
    file_id: int,
    file_name: str,
    preview_cache_key: str | None,
    callback_url: str | None,
) -> None:
    """Single dispatch entry point used by service-layer callers.

    When the fair scheduler is disabled, dispatches directly via
    ``apply_async`` using ``decide_queue(file_name)`` (which handles OCR
    routing). When enabled, enqueues into the per-user virtual queue and
    fires a trigger task to start a dispatch round immediately.
    """
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
        # Captured in the request context so the later (possibly Beat-driven)
        # dispatch round can parse the file under its owning tenant.
        tenant_id=get_current_tenant_id(),
        ttl_seconds=_fair_scheduler_conf().payload_ttl_seconds,
    )
    try:
        trigger_dispatch_task.delay()
    except Exception:
        logger.exception("file_scheduler: trigger_dispatch_task.delay failed; relying on Beat fallback")


# ---------------------------------------------------------------------------
# Reconcile task — fixes Redis ↔ DB drift (Cases 1-4).  Runs every 5 min
# via Celery Beat.
# ---------------------------------------------------------------------------

_TERMINAL_STATUSES: frozenset[int] = frozenset(
    {
        KnowledgeFileStatus.SUCCESS.value,
        KnowledgeFileStatus.FAILED.value,
        KnowledgeFileStatus.TIMEOUT.value,
        KnowledgeFileStatus.VIOLATION.value,
    }
)


@bisheng_celery.task(
    name="bisheng.worker.knowledge.scheduler.reconcile_file_scheduler_task",
    acks_late=True,
)
def reconcile_file_scheduler_task() -> None:
    """Reconcile Redis scheduler state with the DB. Cases 1-4 from the spec."""
    if not _fair_scheduler_enabled():
        return
    conf = _fair_scheduler_conf()
    sched = FileScheduler()

    for user_id in sched.inflight_users():
        for file_id in sched.inflight_files(user_id=user_id):
            # Beat runs under the default tenant, but in-flight files can
            # belong to any tenant. Bypass the auto-injected tenant filter so
            # cross-tenant rows are actually found instead of being mistaken
            # for "missing DB row" (which would silently drop a valid file).
            with bypass_tenant_filter():
                rows = KnowledgeFileDao.get_file_by_ids([int(file_id)])
            if not rows:
                sched.complete_file(user_id=user_id, file_id=file_id)
                logger.warning("reconcile: missing DB row, cleared inflight file_id={}", file_id)
                continue
            row = rows[0]
            status = row.status

            if status in _TERMINAL_STATUSES:
                # Case 1: complete_file callback was lost
                sched.complete_file(user_id=user_id, file_id=file_id)
                logger.warning(
                    "reconcile: leaked inflight (status={}) cleared for file_id={}",
                    status,
                    file_id,
                )
                continue

            if status == KnowledgeFileStatus.WAITING.value:
                # Case 2: apply_async + rollback both failed; re-enqueue
                sched.complete_file(user_id=user_id, file_id=file_id)
                sched.enqueue_file(
                    user_id=user_id,
                    file_id=file_id,
                    preview_cache_key="",
                    callback_url="",
                    file_ext=_extract_ext(row.file_name),
                    tenant_id=getattr(row, "tenant_id", None),
                )
                logger.error("reconcile: re-enqueued orphaned file_id={}", file_id)
                continue

            if status == KnowledgeFileStatus.PROCESSING.value:
                # Case 3: the parse lock is the authoritative liveness signal. A
                # heartbeat refreshes it for the whole parse, so:
                #   - lock ALIVE  → a long-but-healthy parse. Never re-enqueue it,
                #     however long it runs — that would dispatch a concurrent
                #     duplicate parse of the same file (the task-storm OOM bug).
                #   - lock DEAD   → the holding worker crashed/exited and the lock
                #     self-expired once its heartbeat stopped. No one is parsing
                #     this file, so recover it NOW. We deliberately do NOT wait out
                #     inflight_ttl here: a crashed file's queue used to stay blocked
                #     for ~2h; lock liveness lets us recover within one lock-TTL
                #     window plus a reconcile tick instead.
                if sched.parse_lock_alive(file_id=file_id):
                    continue
                sched.complete_file(user_id=user_id, file_id=file_id)
                with bypass_tenant_filter():
                    KnowledgeFileDao.update_file_status(
                        [int(file_id)],
                        KnowledgeFileStatus.WAITING,
                    )
                sched.enqueue_file(
                    user_id=user_id,
                    file_id=file_id,
                    preview_cache_key="",
                    callback_url="",
                    file_ext=_extract_ext(row.file_name),
                    tenant_id=getattr(row, "tenant_id", None),
                )
                logger.error(
                    "reconcile: parse lock dead for stuck PROCESSING file_id={}; re-enqueued",
                    file_id,
                )

    # Case 5: orphaned / ghost queue entries (payload lost while still queued).
    # The dispatch round self-heals these too, but a fully-jammed queue may never
    # advance far enough to reach them; this periodic sweep is the backstop that
    # clears poison pills and restores payloads without manual intervention.
    for user_id in sched.active_users():
        for file_id in sched.queued_files(user_id=user_id):
            if sched.get_payload(file_id=file_id):
                continue  # healthy entry, leave it
            with bypass_tenant_filter():
                rows = KnowledgeFileDao.get_file_by_ids([int(file_id)])
            if not rows or rows[0].status != KnowledgeFileStatus.WAITING.value:
                # Ghost: terminal/deleted → remove from the queue entirely.
                sched.remove_from_queue(user_id=user_id, file_id=file_id)
                logger.warning("reconcile: removed ghost queue entry file_id={}", file_id)
            else:
                # Orphaned WAITING file → rebuild its payload so it can dispatch.
                row = rows[0]
                sched.put_payload(
                    file_id=file_id,
                    preview_cache_key="",
                    callback_url="",
                    user_id=str(user_id),
                    file_ext=_extract_ext(row.file_name),
                    tenant_id=getattr(row, "tenant_id", None),
                    ttl_seconds=conf.payload_ttl_seconds,
                )
                logger.error("reconcile: rebuilt payload for orphaned queued file_id={}", file_id)

    # Case 4: drained active_users
    for user_id in sched.active_users():
        queue_empty = sched._conn.llen(_queue_key(user_id)) == 0
        inflight_empty = sched._conn.scard(_inflight_key(user_id)) == 0
        if queue_empty and inflight_empty:
            sched._conn.srem(ACTIVE_USERS_KEY, user_id)

    # Authoritatively rebuild per-queue in-flight counters from the
    # inflight_queue map, healing any drift from lost confirm/complete calls.
    queues = list(conf.queue_concurrency.keys()) or [KNOWLEDGE_QUEUE]
    if KNOWLEDGE_QUEUE not in queues:
        queues.append(KNOWLEDGE_QUEUE)
    sched.recompute_inflight_totals(queues=queues)
