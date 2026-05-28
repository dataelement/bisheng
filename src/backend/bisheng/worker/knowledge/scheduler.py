"""File parse scheduler — OCR routing helpers and (later tasks) fair dispatch."""

from __future__ import annotations

import uuid

from loguru import logger

from bisheng.common.services.config_service import settings
from bisheng.worker.knowledge.lua_scripts import (
    COMPLETE_FILE,
    DISPATCH_ONE,
    ENQUEUE_FILE,
    RELEASE_LOCK,
    ROLLBACK_DISPATCH,
)

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
DISPATCH_LOCK_KEY = f"{PREFIX}dispatch_lock"


def _queue_key(user_id: str) -> str:
    return f"{PREFIX}queue:{user_id}"


def _payload_key(file_id: str) -> str:
    return f"{PREFIX}payload:{file_id}"


def _inflight_key(user_id: str) -> str:
    return f"{PREFIX}inflight:{user_id}"


class FileScheduler:
    """Sync facade over the Lua scripts for fair-dispatch file scheduling."""

    _PAYLOAD_TTL_SECONDS = 14400  # 4 h, mirrors the Lua script's EXPIRE

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
        self._rollback = self._conn.register_script(ROLLBACK_DISPATCH)
        self._complete = self._conn.register_script(COMPLETE_FILE)
        self._release_lock_script = self._conn.register_script(RELEASE_LOCK)

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
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
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
        self._release_lock_script(keys=[DISPATCH_LOCK_KEY], args=[token])
