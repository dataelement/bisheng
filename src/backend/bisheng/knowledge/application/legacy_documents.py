"""Live legacy document endpoints over the single SPACE business resource."""

import json
from datetime import datetime
from hashlib import sha256

from bisheng.common.cursor import CursorDecodeError, decode_cursor, encode_cursor
from bisheng.common.errcode.knowledge import KnowledgeInvalidCursorError, KnowledgeNoEmbeddingError
from bisheng.common.errcode.llm import WorkbenchEmbeddingError
from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.common.schemas.api import PageInfiniteCursorData
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import KnowledgeRead
from bisheng.knowledge.domain.repositories.knowledge_compatibility_repository import KnowledgeCompatibilityRepository
from bisheng.knowledge.domain.services.knowledge_permission_service import KnowledgePermissionService
from bisheng.permission.application.identity import resolve_permission_actor


class LegacyDocumentsApplication:
    def __init__(self, *, repository=None, space_service=None):
        self.repository = repository or KnowledgeCompatibilityRepository()
        self.space_service = space_service

    @staticmethod
    def view(value, *, actions=None, legacy=True):
        # Always construct a DTO. ORM/source-owner facts keep their actual type.
        result = KnowledgeRead.model_validate(value)
        if legacy and result.type == 3:
            result = result.model_copy(update={"type": 0})
        if actions is not None:
            result = result.model_copy(update={"actions": sorted(actions)})
        return result

    async def acreate(self, *, request, identity, command, entry_kind="web", web_creation_context=None):
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

        model_id = None
        if command.type == 0 and command.model is not None and str(command.model).strip():
            try:
                model_id = int(str(command.model).strip())
            except (TypeError, ValueError) as exc:
                raise KnowledgeNoEmbeddingError() from exc
            if model_id <= 0:
                raise KnowledgeNoEmbeddingError()
        service = self.space_service or KnowledgeSpaceService(request, identity)
        try:
            created = await service.create_knowledge_space(
                name=command.name,
                description=command.description,
                auth_type=command.auth_type,
                is_released=command.is_released,
                auto_tag_enabled=command.auto_tag_enabled,
                auto_tag_library_id=command.auto_tag_library_id,
                embedding_model_id=model_id,
                web_creation_context=web_creation_context,
                entry_kind=entry_kind,
                initial_metadata_fields=command.metadata_fields,
            )
        except WorkbenchEmbeddingError as exc:
            if command.type != 0:
                raise
            raise KnowledgeNoEmbeddingError() from exc
        return self.view(created, legacy=command.type == 0)

    async def alist(
        self,
        *,
        identity,
        name=None,
        sort_by="update_time",
        page_size=10,
        cursor=None,
        preferred_ids=None,
        has_abnormal=False,
        legacy_view=True,
    ):
        sort_by = sort_by if sort_by in {"name", "update_time", "create_time"} else "update_time"
        page_size = max(1, min(int(page_size or 1), 200))
        preferred = tuple(dict.fromkeys(ident for ident in preferred_ids or () if type(ident) is int and ident > 0))
        actor = await resolve_permission_actor(identity)
        filters = sha256(json.dumps([name, preferred, bool(has_abnormal)], separators=(",", ":")).encode()).hexdigest()
        context = (
            f"knowledge_space_legacy|{get_current_tenant_id()}|{actor.subject_type}:{actor.subject_id}|"
            f"{actor.data_scope}|{sort_by}|{filters}"
        )
        is_name = sort_by == "name"
        key_length = 1 if is_name else (3 if preferred else 2)
        try:
            decoded = decode_cursor(cursor, expected_key_len=key_length, expected_context=context)
            offset, after = 0, None
            if decoded is not None:
                if is_name:
                    offset = decoded[0]
                    if type(offset) is not int or offset < 0:
                        raise ValueError("invalid candidate offset")
                else:
                    if type(decoded[-1]) is not int or decoded[-1] <= 0:
                        raise ValueError("invalid candidate ID")
                    timestamp = datetime.fromisoformat(decoded[-2])
                    if preferred:
                        if type(decoded[0]) is not int or decoded[0] not in (0, 1):
                            raise ValueError("invalid preference cursor")
                        after = (decoded[0], timestamp, decoded[-1])
                    else:
                        after = (timestamp, decoded[-1])
        except (CursorDecodeError, ValueError, TypeError) as exc:
            raise KnowledgeInvalidCursorError(exception=exc) from exc
        result, consumed = [], 0

        def page(more):
            return PageInfiniteCursorData[KnowledgeRead](
                data=result,
                page_size=page_size,
                has_more=more,
                next_cursor=encode_cursor([offset] if is_name else after, context=context) if more else None,
            )

        while consumed < 1000:
            limit = min(100, 1000 - consumed)
            rows = await self.repository.alist_space_candidates(
                keyword=name,
                sort_by=sort_by,
                offset=offset,
                after=after,
                limit=limit,
                preferred_ids=preferred,
                has_abnormal=has_abnormal,
            )
            ids = [row.id for row, _ in rows]
            actions = await KnowledgePermissionService.get_knowledge_action_map_async(identity, ids, ["visible"])
            for row, abnormal in rows:
                if len(result) == page_size:
                    return page(True)
                offset += 1
                if not is_name:
                    timestamp = row.create_time if sort_by == "create_time" else row.update_time
                    after = (timestamp, row.id)
                    if preferred:
                        after = (0 if row.id in preferred else 1, *after)
                consumed += 1
                if "visible" in actions.get(row.id, set()):
                    result.append(
                        self.view(row, actions={"visible"}, legacy=legacy_view).model_copy(
                            update={"has_abnormal_files": abnormal}
                        )
                    )
            if len(rows) < limit:
                return page(False)
            if len(result) == page_size:
                break
        pending = await self.repository.alist_space_candidates(
            keyword=name,
            sort_by=sort_by,
            offset=offset,
            after=after,
            limit=1,
            preferred_ids=preferred,
            has_abnormal=has_abnormal,
        )
        return page(bool(pending))

    async def anormalize_permission_resource(self, resource_type: str, resource_id: str) -> str:
        if resource_type.strip().lower() != "knowledge_library":
            return resource_type
        resource_id = resource_id.strip()
        if not resource_id.isdecimal() or str(int(resource_id)) != resource_id or not 0 < int(resource_id) <= 2**63 - 1:
            raise PermissionInvalidResourceError()
        actual = (await self.repository.aresource_types([int(resource_id)])).get(int(resource_id))
        if actual is None:
            raise PermissionInvalidResourceError()
        return actual
