"""Celery worker for extracting document titles and generating AI aliases."""

import os
import tempfile

from loguru import logger

from bisheng.core.logger import trace_id_var
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao, KnowledgeFileStatus
from bisheng.knowledge.domain.services.file_alias_name_generator import (
    FileAliasNameGeneratorService,
)
from bisheng.knowledge.domain.services.file_title_extractor import FileTitleExtractorService
from bisheng.utils.file import download_minio_file
from bisheng.worker.main import bisheng_celery


def _extract_and_generate_alias(file_id: int) -> str | None:
    """Download the file, extract its title, generate an AI alias, and persist it.

    Returns the generated alias name, or ``None`` if no alias was generated. All
    failures are logged and swallowed because this is a best-effort step that
    must not block the main parsing flow.
    """
    db_file = KnowledgeFileDao.query_by_id_sync(file_id)
    if not db_file:
        logger.warning("title extraction skipped, file not found file_id={}", file_id)
        return None

    if db_file.status != KnowledgeFileStatus.WAITING.value:
        logger.info(
            "title extraction skipped, file status={} file_id={}",
            db_file.status,
            file_id,
        )
        return None

    if not db_file.object_name:
        logger.warning("title extraction skipped, missing object_name file_id={}", file_id)
        return None

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            local_path, _ = download_minio_file(
                object_name=db_file.object_name,
                root_dir=tmp_dir,
                calc_sha256=False,
            )
            if not local_path or not os.path.exists(local_path):
                logger.warning("title extraction skipped, download failed file_id={}", file_id)
                return None

            raw_title = FileTitleExtractorService.extract_title(local_path)
            if not raw_title:
                logger.info("no title extracted file_id={} file_name={}", file_id, db_file.file_name)
                return None

            alias_name = FileAliasNameGeneratorService.generate_alias_name(
                file_path=local_path,
                file_name=db_file.file_name,
                extracted_title=raw_title,
                invoke_user_id=db_file.user_id or 0,
                tenant_id=db_file.tenant_id or 1,
            )
            if alias_name and alias_name != db_file.alias_name:
                db_file.alias_name = alias_name
                KnowledgeFileDao.update(db_file)
                logger.info(
                    "file alias generated file_id={} file_name={} alias_name={}",
                    file_id,
                    db_file.file_name,
                    alias_name,
                )
            else:
                logger.info(
                    "no alias generated file_id={} file_name={} title={}",
                    file_id,
                    db_file.file_name,
                    raw_title,
                )
            return alias_name
    except Exception as e:
        # Alias generation is best-effort; failures must not block parsing.
        logger.warning("title extraction / alias generation failed file_id={} error={}", file_id, e)
    return None


@bisheng_celery.task(acks_late=True)
def extract_knowledge_file_title_celery(
    file_id: int,
    preview_cache_key: str | None = None,
    callback_url: str | None = None,
):
    """Extract the title of an uploaded file, generate an AI alias, then parse.

    This task runs after a knowledge file record has been created and before the
    main parsing task. When a title is successfully extracted, an LLM is asked to
    produce a normalized alias which is persisted in ``KnowledgeFile.alias_name``.
    The task always dispatches ``parse_knowledge_file_celery`` so parsing proceeds
    regardless of title extraction or alias generation success.
    """
    trace_id_var.set(f"extract_title_{file_id}")
    logger.info(
        "extract_knowledge_file_title_celery start file_id={} preview_cache_key={}",
        file_id,
        preview_cache_key,
    )
    try:
        _extract_and_generate_alias(file_id)
    except Exception as e:
        # Defensive catch: _extract_and_generate_alias already swallows its own
        # errors, but we keep this guard so the downstream parse task is never
        # skipped because of an unexpected failure.
        logger.warning(
            "unexpected error during title extraction file_id={} error={}",
            file_id,
            e,
        )
    finally:
        try:
            from bisheng.worker.knowledge.file_worker import parse_knowledge_file_celery

            parse_knowledge_file_celery.delay(file_id, preview_cache_key, callback_url)
            logger.info(
                "enqueued parse task after title extraction file_id={}",
                file_id,
            )
        except Exception as e:
            logger.error(
                "failed to enqueue parse after title extraction file_id={} error={}",
                file_id,
                e,
            )
