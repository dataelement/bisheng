"""补全历史空间知识库文件的二级分类。

新上传文件会在解析链路中生成二级分类, 而字段上线前的历史文件需要
一次性补全。本脚本默认只扫描和统计; 仅 `--apply` 会读取门户配置、
Elasticsearch 和工作台 LLM, 并将结果写入仍为空的分类字段。

从 `src/backend` 执行:

    PYTHONPATH=./ .venv/bin/python scripts/backfill_file_subcategories.py
    PYTHONPATH=./ .venv/bin/python scripts/backfill_file_subcategories.py --apply --file-id 123
    PYTHONPATH=./ .venv/bin/python scripts/backfill_file_subcategories.py --apply --limit 200 --sleep-ms 100

正式执行会产生 Elasticsearch 读取和 LLM 调用成本, 且脚本不提供自动回滚。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import and_, func, or_  # noqa: E402
from sqlmodel import col, select, update  # noqa: E402
from sqlmodel.ext.asyncio.session import AsyncSession  # noqa: E402

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum  # noqa: E402
from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.core.context.tenant import (  # noqa: E402
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    strict_tenant_filter,
)
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.core.database.tenant_filter import build_tenant_filter_clause  # noqa: E402
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag  # noqa: E402
from bisheng.knowledge.domain.models.knowledge import (  # noqa: E402
    Knowledge,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_file import (  # noqa: E402
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.knowledge.rag.pipeline.transformer.file_encoding import (  # noqa: E402
    CONTENT_HEAD_CHARS,
    FileEncodingTransformer,
    FileSubcategoryOption,
)
from bisheng.llm.domain.services.llm import LLMService  # noqa: E402
from bisheng.shougang_portal_config.domain.services.portal_config_service import (  # noqa: E402
    ShougangPortalConfigService,
)

MAX_AI_ATTEMPTS = 3
SYSTEM_INVOKE_USER_ID = 0
ES_PAGE_SIZE = 1000

SkipReason = Literal[
    "invalid_file_encoding",
    "portal_config_unavailable",
    "parent_not_configured",
    "no_valid_candidates",
    "knowledge_index_missing",
    "es_read_failed",
    "es_content_empty",
    "llm_config_missing",
    "ai_attempts_exhausted",
    "concurrent_fill_skipped",
]


@dataclass(frozen=True)
class OptionsResolution:
    """门户二级分类候选解析结果。"""

    options: tuple[FileSubcategoryOption, ...] = ()
    reason: SkipReason | None = None


@dataclass(frozen=True)
class ContentHeadResult:
    """Elasticsearch 正文开头读取结果。"""

    content: str = ""
    reason: SkipReason | None = None


@dataclass(frozen=True)
class AISelection:
    """AI 候选选择结果及实际尝试次数。"""

    option: FileSubcategoryOption | None = None
    attempts: int = 0
    reason: SkipReason | None = None


@dataclass(frozen=True)
class ProcessResult:
    """单文件处理结果。"""

    status: Literal["saved", "skipped", "concurrent"]
    source: Literal["ai", "fallback"] | None = None
    reason: SkipReason | None = None
    attempts: int = 0


@dataclass(frozen=True)
class BackfillDetail:
    """跳过或异常文件的脱敏定位信息。"""

    file_id: int
    tenant_id: int
    knowledge_id: int
    reason: str
    error_type: str | None = None


@dataclass
class BackfillReport:
    """补全任务的可观测摘要。"""

    total_scanned: int = 0
    eligible: int = 0
    would_process: int = 0
    fallback_saved: int = 0
    ai_saved: int = 0
    concurrent_fill_skipped: int = 0
    skipped_by_reason: dict[str, int] = field(default_factory=dict)
    unexpected_errors: int = 0
    details: list[BackfillDetail] = field(default_factory=list)

    def add_skip(self, knowledge_file: KnowledgeFile, reason: str) -> None:
        self.skipped_by_reason[reason] = self.skipped_by_reason.get(reason, 0) + 1
        self.details.append(_detail_for_file(knowledge_file, reason=reason))

    def add_unexpected_error(self, knowledge_file: KnowledgeFile, exc: Exception) -> None:
        self.unexpected_errors += 1
        self.details.append(
            _detail_for_file(
                knowledge_file,
                reason="unexpected_error",
                error_type=type(exc).__name__,
            )
        )

    def summary(self) -> dict[str, Any]:
        return {
            "total_scanned": self.total_scanned,
            "eligible": self.eligible,
            "would_process": self.would_process,
            "fallback_saved": self.fallback_saved,
            "ai_saved": self.ai_saved,
            "concurrent_fill_skipped": self.concurrent_fill_skipped,
            "skipped_by_reason": dict(sorted(self.skipped_by_reason.items())),
            "unexpected_errors": self.unexpected_errors,
        }

    def __str__(self) -> str:
        return json.dumps(self.summary(), ensure_ascii=False, sort_keys=True)


def _detail_for_file(
    knowledge_file: KnowledgeFile,
    *,
    reason: str,
    error_type: str | None = None,
) -> BackfillDetail:
    return BackfillDetail(
        file_id=int(knowledge_file.id),
        tenant_id=int(knowledge_file.tenant_id),
        knowledge_id=int(knowledge_file.knowledge_id),
        reason=reason,
        error_type=error_type,
    )


def _blank_subcategory_predicate():
    return or_(
        col(KnowledgeFile.file_subcategory_code).is_(None),
        func.trim(col(KnowledgeFile.file_subcategory_code)) == "",
    )


def _candidate_stmt(
    *,
    tenant_id: int | None,
    knowledge_id: int | None,
    file_id: int | None,
    last_id: int,
    batch_size: int,
):
    stmt = (
        select(KnowledgeFile, Knowledge)
        .join(
            Knowledge,
            and_(
                KnowledgeFile.knowledge_id == Knowledge.id,
                KnowledgeFile.tenant_id == Knowledge.tenant_id,
            ),
        )
        .where(
            Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            KnowledgeFile.id > last_id,
            KnowledgeFile.file_type == FileType.FILE.value,
            KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
            _blank_subcategory_predicate(),
        )
        .order_by(KnowledgeFile.id)
        .limit(batch_size)
    )
    if tenant_id is not None:
        stmt = stmt.where(KnowledgeFile.tenant_id == tenant_id)
    if knowledge_id is not None:
        stmt = stmt.where(KnowledgeFile.knowledge_id == knowledge_id)
    if file_id is not None:
        stmt = stmt.where(KnowledgeFile.id == file_id)
    return stmt


def _extract_document_type_code(file_encoding: str | None) -> str | None:
    """复用在线链路的文档类型提取规则。"""
    return FileEncodingTransformer._extract_document_type_code_from_file_encoding(file_encoding)


def _item_to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    model_dump = getattr(item, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return {
        "code": getattr(item, "code", None),
        "label": getattr(item, "label", None),
        "children": getattr(item, "children", None),
    }


async def _load_subcategory_options(
    knowledge_file: KnowledgeFile,
    transformer: FileEncodingTransformer,
) -> OptionsResolution:
    parent_code = _extract_document_type_code(knowledge_file.file_encoding)
    if not parent_code:
        return OptionsResolution(reason="invalid_file_encoding")

    try:
        config = await ShougangPortalConfigService.get_config(tenant_id=int(knowledge_file.tenant_id))
    except Exception:
        return OptionsResolution(reason="portal_config_unavailable")
    if config is None:
        return OptionsResolution(reason="portal_config_unavailable")

    document_types = getattr(getattr(config, "portal", None), "document_types", None)
    if not isinstance(document_types, list) or not document_types:
        return OptionsResolution(reason="portal_config_unavailable")

    matched_parent: dict[str, Any] | None = None
    for item in document_types:
        raw_item = _item_to_dict(item)
        code = transformer._normalize_document_type_code(raw_item.get("code"))
        if code == parent_code:
            matched_parent = raw_item
            break
    if matched_parent is None:
        return OptionsResolution(reason="parent_not_configured")

    children = matched_parent.get("children")
    if not isinstance(children, list) or not children:
        return OptionsResolution(reason="no_valid_candidates")

    valid_child_codes = {
        code
        for child in children
        if (code := transformer._normalize_file_subcategory_code(_item_to_dict(child).get("code")))
    }
    if not valid_child_codes:
        return OptionsResolution(reason="no_valid_candidates")
    options_by_parent = transformer._resolve_subcategory_options_by_document_type([matched_parent])
    options = tuple(option for option in (options_by_parent.get(parent_code) or ()) if option.code in valid_child_codes)
    if not options:
        return OptionsResolution(reason="no_valid_candidates")
    return OptionsResolution(options=options)


def _normalize_chunk(hit: dict[str, Any]) -> dict[str, Any]:
    source = hit.get("_source") or {}
    metadata = source.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "id": hit.get("_id"),
        "text": source.get("text", ""),
        "metadata": metadata,
    }


def _chunk_sort_key(chunk: dict[str, Any]) -> tuple[int, int | str, str]:
    chunk_index = chunk["metadata"].get("chunk_index")
    try:
        return 0, int(chunk_index), str(chunk["id"] or "")
    except (TypeError, ValueError):
        return 1, str(chunk_index or ""), str(chunk["id"] or "")


def _read_content_head_sync(knowledge: Knowledge, file_id: int) -> ContentHeadResult:
    """同步读取 ES; 外层在线程中调用, 避免阻塞事件循环。"""
    if not getattr(knowledge, "index_name", None):
        return ContentHeadResult(reason="knowledge_index_missing")

    scroll_id: str | None = None
    client = None
    try:
        store = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=knowledge)
        client = store.client
        response = client.search(
            index=knowledge.index_name,
            query={"term": {"metadata.document_id": file_id}},
            size=ES_PAGE_SIZE,
            scroll="1m",
            source=True,
        )
        chunks: list[dict[str, Any]] = []
        scroll_id = response.get("_scroll_id")
        while True:
            hits = response.get("hits", {}).get("hits", [])
            if not hits:
                break
            chunks.extend(_normalize_chunk(hit) for hit in hits)
            if not scroll_id:
                break
            response = client.scroll(scroll_id=scroll_id, scroll="1m")
            scroll_id = response.get("_scroll_id", scroll_id)
    except Exception:
        return ContentHeadResult(reason="es_read_failed")
    finally:
        if client is not None and scroll_id:
            try:
                client.clear_scroll(scroll_id=scroll_id)
            except Exception:
                # 清理失败不得覆盖已获得的只读结果。
                pass

    if not chunks:
        return ContentHeadResult(reason="es_content_empty")
    chunks.sort(key=_chunk_sort_key)
    text = "\n".join(str(chunk.get("text") or "") for chunk in chunks)
    content = re.sub(r"\s+", " ", text).strip()[:CONTENT_HEAD_CHARS]
    if not content:
        return ContentHeadResult(reason="es_content_empty")
    return ContentHeadResult(content=content)


async def _read_content_head(knowledge: Knowledge, file_id: int) -> ContentHeadResult:
    return await asyncio.to_thread(_read_content_head_sync, knowledge, file_id)


async def _select_with_ai(
    transformer: FileEncodingTransformer,
    options: tuple[FileSubcategoryOption, ...],
) -> AISelection:
    tenant_id = int(transformer.knowledge_file.tenant_id)
    try:
        llm_config = await LLMService.get_workbench_llm(tenant_id=tenant_id)
    except Exception:
        return AISelection(reason="llm_config_missing")
    model_id = getattr(getattr(llm_config, "chat_title_llm", None), "id", None)
    if not model_id:
        return AISelection(reason="llm_config_missing")

    messages = transformer._build_subcategory_messages(options)
    for attempt in range(1, MAX_AI_ATTEMPTS + 1):
        try:
            llm = await LLMService.get_bisheng_llm(
                model_id=model_id,
                app_id=ApplicationTypeEnum.DAILY_CHAT.value,
                app_name="shougang_file_subcategory_backfill",
                app_type=ApplicationTypeEnum.DAILY_CHAT,
                user_id=SYSTEM_INVOKE_USER_ID,
                temperature=0,
            )
            response = await llm.ainvoke(messages)
            selected_code = transformer._normalize_file_subcategory_code(
                str(getattr(response, "content", "") or "").strip()
            )
            selected = next((option for option in options if option.code == selected_code), None)
            if selected is not None:
                return AISelection(option=selected, attempts=attempt)
        except Exception:
            # 调用异常与无效响应都消耗一次尝试, 不记录 prompt 或正文。
            continue
    return AISelection(attempts=MAX_AI_ATTEMPTS, reason="ai_attempts_exhausted")


async def _conditional_write(
    session: AsyncSession,
    *,
    file_id: int,
    code: str,
    source: Literal["ai", "fallback"],
) -> bool:
    tenant_clause = build_tenant_filter_clause(col(KnowledgeFile.tenant_id))
    if tenant_clause is None:
        raise RuntimeError("tenant context is required for subcategory update")
    stmt = (
        update(KnowledgeFile)
        .where(
            KnowledgeFile.id == file_id,
            tenant_clause,
            _blank_subcategory_predicate(),
        )
        .values(
            file_subcategory_code=code,
            file_subcategory_source=source,
        )
    )
    try:
        result = await session.exec(stmt)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return int(result.rowcount or 0) == 1


async def process_file(
    session: AsyncSession,
    knowledge_file: KnowledgeFile,
    knowledge: Knowledge,
) -> ProcessResult:
    transformer = FileEncodingTransformer(
        invoke_user_id=SYSTEM_INVOKE_USER_ID,
        knowledge_file=knowledge_file,
    )
    resolution = await _load_subcategory_options(knowledge_file, transformer)
    if resolution.reason:
        return ProcessResult(status="skipped", reason=resolution.reason)

    options = resolution.options
    if len(options) == 1:
        selected = options[0]
        source: Literal["ai", "fallback"] = "fallback"
        attempts = 0
    else:
        content_result = await _read_content_head(knowledge, int(knowledge_file.id))
        if content_result.reason:
            return ProcessResult(status="skipped", reason=content_result.reason)
        transformer.content_head = content_result.content
        ai_selection = await _select_with_ai(transformer, options)
        if ai_selection.option is None:
            return ProcessResult(
                status="skipped",
                reason=ai_selection.reason or "ai_attempts_exhausted",
                attempts=ai_selection.attempts,
            )
        selected = ai_selection.option
        source = "ai"
        attempts = ai_selection.attempts

    saved = await _conditional_write(
        session,
        file_id=int(knowledge_file.id),
        code=selected.code,
        source=source,
    )
    if not saved:
        return ProcessResult(
            status="concurrent",
            reason="concurrent_fill_skipped",
            attempts=attempts,
        )
    return ProcessResult(status="saved", source=source, attempts=attempts)


def _record_process_result(
    report: BackfillReport,
    knowledge_file: KnowledgeFile,
    result: ProcessResult,
) -> None:
    if result.status == "saved":
        if result.source == "fallback":
            report.fallback_saved += 1
        else:
            report.ai_saved += 1
        return
    if result.status == "concurrent":
        report.concurrent_fill_skipped += 1
        report.details.append(_detail_for_file(knowledge_file, reason="concurrent_fill_skipped"))
        return
    report.add_skip(knowledge_file, result.reason or "unknown_skip")


async def backfill(
    session: AsyncSession,
    *,
    apply: bool = False,
    tenant_id: int | None = None,
    knowledge_id: int | None = None,
    file_id: int | None = None,
    limit: int | None = None,
    batch_size: int = 50,
    sleep_ms: int = 0,
) -> BackfillReport:
    report = BackfillReport()
    last_id = 0
    remaining = limit

    while remaining is None or remaining > 0:
        current_batch_size = batch_size if remaining is None else min(batch_size, remaining)
        with bypass_tenant_filter():
            rows = list(
                (
                    await session.exec(
                        _candidate_stmt(
                            tenant_id=tenant_id,
                            knowledge_id=knowledge_id,
                            file_id=file_id,
                            last_id=last_id,
                            batch_size=current_batch_size,
                        )
                    )
                ).all()
            )
        if not rows:
            break

        report.total_scanned += len(rows)
        report.eligible += len(rows)
        for knowledge_file, knowledge in rows:
            last_id = max(last_id, int(knowledge_file.id))
            if not apply:
                report.would_process += 1
                continue

            token = set_current_tenant_id(int(knowledge_file.tenant_id))
            try:
                with strict_tenant_filter():
                    result = await process_file(session, knowledge_file, knowledge)
            except Exception as exc:
                report.add_unexpected_error(knowledge_file, exc)
            else:
                _record_process_result(report, knowledge_file, result)
            finally:
                current_tenant_id.reset(token)

        if remaining is not None:
            remaining -= len(rows)
        if sleep_ms > 0:
            await asyncio.sleep(sleep_ms / 1000)

    return report


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return number


def _non_negative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("must be greater than or equal to 0")
    return number


async def _run(args: argparse.Namespace) -> int:
    try:
        async with get_async_db_session() as session:
            report = await backfill(
                session,
                apply=args.apply,
                tenant_id=args.tenant_id,
                knowledge_id=args.knowledge_id,
                file_id=args.file_id,
                limit=args.limit,
                batch_size=args.batch_size,
                sleep_ms=args.sleep_ms,
            )
        print(report)
        for detail in report.details:
            print(json.dumps(asdict(detail), ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1 if report.unexpected_errors else 0
    finally:
        await close_app_context()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true", help="执行 ES/AI 分类并写入; 默认仅扫描。")
    parser.add_argument("--tenant-id", type=_positive_int, default=None, help="仅处理指定租户。")
    parser.add_argument("--knowledge-id", type=_positive_int, default=None, help="仅处理指定知识库。")
    parser.add_argument("--file-id", type=_positive_int, default=None, help="仅处理指定 KnowledgeFile。")
    parser.add_argument("--limit", type=_positive_int, default=None, help="最多扫描 N 个符合条件的文件。")
    parser.add_argument("--batch-size", type=_positive_int, default=50, help="数据库批次大小, 默认 50。")
    parser.add_argument("--sleep-ms", type=_non_negative_int, default=0, help="每批完成后等待毫秒数。")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
