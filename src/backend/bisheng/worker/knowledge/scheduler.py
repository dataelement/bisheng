"""File parse scheduler — OCR routing helpers and (later tasks) fair dispatch."""

from __future__ import annotations

from loguru import logger

from bisheng.common.services.config_service import settings

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
