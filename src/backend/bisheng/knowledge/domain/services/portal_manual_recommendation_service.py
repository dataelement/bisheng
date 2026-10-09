from collections.abc import Awaitable, Callable
from pathlib import Path

from bisheng.common.errcode.knowledge_space import PortalManualRecommendationInvalidError
from bisheng.knowledge.domain.repositories.interfaces.portal_manual_recommendation_repository import (
    ManualFileRecord,
    PortalManualRecommendationRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalFileBrowseReq


class PortalManualRecommendationService:
    def __init__(self, repository: PortalManualRecommendationRepository):
        self.repository = repository

    @staticmethod
    def identity(item: dict) -> tuple:
        document_id = item.get("canonical_document_id")
        return (
            ("document", int(document_id))
            if document_id
            else ("file", int(item["space_id"]), int(item.get("file_id") or item["id"]))
        )

    @staticmethod
    def _find(reference: dict, records: list[ManualFileRecord], *, refresh: bool) -> ManualFileRecord | None:
        candidates = [row for row in records if row.file.knowledge_id == reference["space_id"]]
        document_id = reference.get("canonical_document_id")
        if document_id:
            candidates = [row for row in candidates if row.canonical_document_id == document_id]
        exact = next((row for row in candidates if row.file.id == reference["file_id"]), None)
        return exact or (candidates[0] if refresh and document_id and candidates else None)

    @staticmethod
    def metadata(row: ManualFileRecord) -> dict:
        file = row.file
        updated = file.update_time or file.create_time
        return {
            "id": int(file.id),
            "space_id": int(file.knowledge_id),
            "title": Path(file.file_name).stem,
            "summary": file.abstract or "",
            "source": row.space_name,
            "updated_at": updated.isoformat() if updated else "",
            "file_ext": Path(file.file_name).suffix.lstrip(".").lower(),
            "file_subcategory_code": file.file_subcategory_code or "",
            "canonical_document_id": row.canonical_document_id,
            "entry_type": file.entry_type or "normal",
            "entry_status": file.entry_status or "active",
            "content_access": "check_required",
            "can_download": False,
            "is_department_file": row.space_level != "public",
            "space_level": "team" if row.space_level == "team_ks" else row.space_level,
            "is_clinic": row.space_level in {"team", "team_ks"},
            "capabilities": {"can_view": False, "can_download": False},
        }

    async def validate_items(self, items: list[dict], previous: list[dict]) -> list[dict]:
        records = await self.repository.find_references(items)
        prior = {(ref["space_id"], ref["file_id"], ref.get("canonical_document_id")) for ref in previous}
        result, seen = [], set()
        for reference in items:
            ref = dict(reference)
            existing = (ref["space_id"], ref["file_id"], ref.get("canonical_document_id")) in prior
            record = self._find(ref, records, refresh=existing)
            if record is None and not existing:
                raise PortalManualRecommendationInvalidError()
            if record:
                ref["canonical_document_id"] = record.canonical_document_id
            identity = self.identity(ref)
            if identity in seen:
                raise PortalManualRecommendationInvalidError(msg="同一知识不能重复加入人工推荐")
            seen.add(identity)
            result.append(ref)
        return result

    async def resolve_items(self, references: list[dict]) -> list[dict]:
        records = await self.repository.find_references(references)
        result, seen = [], set()
        for ref in references:
            record = self._find(ref, records, refresh=True)
            if record:
                metadata = self.metadata(record)
                identity = self.identity(metadata)
                if identity not in seen:
                    seen.add(identity)
                    result.append(metadata)
        return result

    async def list_spaces(self) -> dict:
        return {"options": await self.repository.list_spaces()}

    async def list_files(self, space_id: int, q: str, page: int, page_size: int) -> dict:
        rows, total = await self.repository.list_files(space_id, q, page, page_size)
        return {"data": [self.metadata(row) for row in rows], "total": total, "page": page, "page_size": page_size}

    async def selected_items(self, references: list[dict]) -> dict:
        records = await self.repository.find_references(references)
        return {
            "items": [
                {
                    **ref,
                    "valid": bool(record),
                    "item": self.metadata(record) if record else None,
                    "reason": "" if record else "知识已失效或不在可选范围",
                }
                for ref in references
                for record in [self._find(ref, records, refresh=True)]
            ]
        }

    async def recommend(
        self,
        req: ShougangPortalFileBrowseReq,
        references: list[dict],
        fetch_automatic: Callable[[ShougangPortalFileBrowseReq], Awaitable[dict]],
        *,
        config_version: int,
        tenant_id: int,
        user_id: int,
        total_count: int,
        display_count: int = 6,
        accept_record: Callable[[ManualFileRecord], bool] | None = None,
        scope_signature: str = "",
    ) -> dict:
        import hashlib
        import json

        from loguru import logger

        from bisheng.common.cursor import CursorDecodeError, decode_cursor, encode_cursor
        from bisheng.common.errcode.knowledge import KnowledgeInvalidCursorError

        try:
            records = await self.repository.find_references(references)
            manual, seen = [], set()
            for ref in references:
                row = self._find(ref, records, refresh=True)
                if row is None or (accept_record and not accept_record(row)):
                    continue
                item = self.metadata(row)
                query = str(getattr(req, "q", "") or "").strip().casefold()
                if query and query not in (item["title"] + " " + item["summary"]).casefold():
                    continue
                if req.response_scene != "home" and req.space_ids and item["space_id"] not in req.space_ids:
                    continue
                if req.response_scene != "home" and req.space_level and item["space_level"] != req.space_level.value:
                    continue
                if req.file_ext and item["file_ext"] != req.file_ext.lstrip(".").lower():
                    continue
                key = self.identity(item)
                if key not in seen:
                    seen.add(key)
                    manual.append(item)
        except Exception:
            # 可选人工引用复核失败时,不返回未经确认的人工元数据;自动路径继续。
            logger.exception("人工推荐引用复核失败,使用安全自动结果")
            manual, seen = [], set()
        signature = {
            **req.model_dump(mode="json", exclude={"cursor", "limit", "response_scene"}),
            "tenant": tenant_id,
            "user": user_id,
            "version": config_version,
            "scope_snapshot": scope_signature,
            "manual": [(item["space_id"], item["id"], item.get("canonical_document_id")) for item in manual],
        }
        context = "portal-manual:" + hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
        personalized = req.recommendation == "personalized_v1"
        offset = 0
        if req.cursor:
            try:
                key = decode_cursor(req.cursor, expected_key_len=1, expected_context=context)
                offset = key[0]
                if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 2_147_483_647:
                    raise CursorDecodeError("invalid manual offset")
            except (CursorDecodeError, TypeError, IndexError) as exc:
                raise KnowledgeInvalidCursorError(exception=exc) from exc
        page_limit = total_count if personalized else req.limit
        desired = total_count if personalized else offset + page_limit + 1
        combined = list(manual)
        source_cursor, source_seen, exhausted = None, set(), False
        snapshot = ""
        while len(combined) < desired and not exhausted:
            auto_req = req.model_copy(
                update={
                    "cursor": source_cursor,
                    "limit": min(total_count, 100) if personalized else 100,
                    "response_scene": "list",
                }
            )
            result = await fetch_automatic(auto_req)
            snapshot = result.get("discovery_snapshot", snapshot)
            for item in result.get("data") or []:
                key = self.identity(item)
                if key not in seen:
                    seen.add(key)
                    combined.append(item)
                if len(combined) >= desired:
                    break
            next_cursor = result.get("next_cursor")
            exhausted = personalized or not result.get("has_more") or not next_cursor
            if next_cursor in source_seen:
                raise RuntimeError("人工推荐自动分页游标重复")
            if next_cursor:
                source_seen.add(next_cursor)
            source_cursor = next_cursor
        if personalized:
            combined = combined[:total_count]
            if req.response_scene == "home":
                data = combined[:display_count]
            else:
                data = combined
            return {
                "data": data,
                "total": len(combined),
                "has_more": False,
                "next_cursor": None,
                "discovery_snapshot": snapshot,
            }
        has_more = len(combined) > offset + page_limit
        return {
            "data": combined[offset : offset + page_limit],
            "has_more": has_more,
            "next_cursor": encode_cursor((offset + page_limit,), context=context) if has_more else None,
            "discovery_snapshot": snapshot,
        }
