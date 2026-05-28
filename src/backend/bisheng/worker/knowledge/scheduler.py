"""File parse scheduler — OCR routing helpers and (later tasks) fair dispatch."""

from __future__ import annotations

from loguru import logger

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
        (knowledge_conf.etl4lm.url or "") or (knowledge_conf.mineru.url or "") or (knowledge_conf.paddle_ocr.url or "")
    )


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
