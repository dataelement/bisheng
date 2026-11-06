"""Visible history and bounded candidate reads; version writes stay separate."""

import json
from hashlib import sha256

from bisheng.common.cursor import decode_cursor, encode_cursor
from bisheng.common.errcode.knowledge_space import KnowledgeSpaceInvalidCursorError, SpaceFileNotFoundError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import (
    get_admin_scope_tenant_id,
    get_current_tenant_id,
    get_is_management_api,
    is_tenant_filter_bypassed,
)
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
from bisheng.knowledge.domain.repositories.knowledge_version_read_repository import KnowledgeVersionReadRepository
from bisheng.knowledge.domain.schemas.knowledge_version_schema import (
    AssociableDocumentEntry,
    VersionCandidatePage,
    VersionEntry,
    VersionListResponse,
)
from bisheng.open_api.domain.context import get_current_open_api_principal
from bisheng.permission.application.access import get_f048_resource_adapter
from bisheng.permission.application.business_authorization import (
    batch_check_business_actions,
    batch_check_verified_business_visible,
)
from bisheng.permission.application.identity import resolve_permission_actor
from bisheng.permission.domain.services.data_scope import DATA_SCOPE_ALL


class KnowledgeVersionReadService:
    def __init__(self, request, login_user, *, repository=None, permission_adapter=None):
        self.request, self.login_user = request, login_user
        self.repository = repository if repository is not None else KnowledgeVersionReadRepository()
        self._adapter = permission_adapter

    def _management_super(self, actor, tenant_id):
        return (
            actor.subject_type == "user"
            and actor.subject_id == self.login_user.user_id
            and actor.current_tenant_id == self.login_user.tenant_id
            and actor.super_admin
            and actor.data_scope == DATA_SCOPE_ALL
            and get_is_management_api()
            and get_admin_scope_tenant_id() == tenant_id == get_current_tenant_id()
        )

    async def _context(self):
        actor, tenant_id = await resolve_permission_actor(self.login_user), get_current_tenant_id()
        management_super = self._management_super(actor, tenant_id)
        if (
            type(tenant_id) is not int
            or tenant_id <= 0
            or is_tenant_filter_bypassed()
            or (actor.current_tenant_id != tenant_id and not management_super)
        ):
            raise PermissionDeniedError()
        return actor, tenant_id, management_super

    async def _visible(self, anchor, rows, context):
        if not rows:
            return set()
        actor, _, management_super = context
        adapter = self._adapter or await get_f048_resource_adapter("knowledge_file")
        targets = await adapter.resolve_permission_targets_from_rows(
            rows=rows, knowledge=anchor.space, actor=actor, action="visible"
        )
        if management_super:
            actions = await batch_check_business_actions(
                self.login_user,
                resource_type="knowledge_file",
                resource_ids=(target.resource_id for target in targets),
                actions=("visible",),
            )
            return {int(ident) for ident, codes in actions.items() if "visible" in codes}
        visible = await batch_check_verified_business_visible(actor=actor, targets=targets)
        return {
            int(target.resource_id) for target in targets if visible.get(("knowledge_file", target.resource_id), False)
        }

    async def _anchor(self, file_id, knowledge_id=None):
        context = await self._context()
        anchor = await self.repository.aget_anchor(tenant_id=context[1], file_id=file_id)
        if anchor is None or (knowledge_id is not None and anchor.space.id != knowledge_id):
            raise SpaceFileNotFoundError()
        if anchor.file.id not in await self._visible(anchor, [anchor.file], context):
            raise PermissionDeniedError()
        return anchor, context

    async def list_versions_for_file(self, knowledge_file_id):
        anchor, context = await self._anchor(knowledge_file_id)
        entries, primary, count, after = [], None, 0, None
        while True:
            batch = await self.repository.alist_chain(
                tenant_id=context[1], document_id=anchor.document.id, after_version_id=after
            )
            visible = await self._visible(anchor, [fact.file for fact in batch.data], context)
            count += len(batch.data)
            for fact in batch.data:
                version, file = fact.version, fact.file
                if file.id not in visible:
                    continue
                if version.is_primary:
                    primary = fact
                entries.append(
                    VersionEntry(
                        version_id=version.id,
                        version_no=version.version_no,
                        is_primary=version.is_primary,
                        knowledge_file_id=file.id,
                        original_file_name=file.file_name,
                        file_code=file.file_encoding,
                        uploader_name=file.user_name,
                        uploader_id=file.user_id,
                        upload_time=file.create_time,
                        status=file.status,
                    )
                )
            if not batch.has_more:
                break
            after = batch.next_after
        if count != anchor.version_count:
            raise SpaceFileNotFoundError()
        header = primary.file if primary else anchor.file
        return VersionListResponse(
            document_id=anchor.document.id,
            knowledge_id=anchor.space.id,
            title=header.file_name,
            doc_code=header.file_encoding,
            current_primary_version_no=primary.version.version_no if primary else None,
            versions=sorted(entries, key=lambda item: item.version_no),
        )

    def _cursor_context(self, context, knowledge_id, current_file_id, keyword, source_only, page_size):
        actor, tenant_id, _ = context
        principal = get_current_open_api_principal()
        credential = (
            None
            if principal is None
            else [
                principal.credential_id,
                principal.mode,
                sorted(principal.scopes),
                principal.authorization_subject_type,
                principal.authorization_subject_id,
                principal.effective_user_id,
                principal.preview_session_id,
                principal.preview_version_id,
            ]
        )
        values = [
            tenant_id,
            actor.fga_subject,
            actor.current_tenant_id,
            actor.data_scope,
            actor.super_admin,
            sorted(actor.tenant_admin_tenant_ids),
            self.login_user.user_id,
            self.login_user.tenant_id,
            get_is_management_api(),
            get_admin_scope_tenant_id(),
            credential,
            knowledge_id,
            current_file_id,
            keyword,
            source_only,
            page_size,
        ]
        return "knowledge-version-candidates|" + sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _entry(fact):
        return AssociableDocumentEntry(
            document_id=fact.document.id,
            title=fact.file.file_name,
            doc_code=fact.file.file_encoding,
            current_primary_version_no=fact.version.version_no,
            primary_uploader_name=fact.file.user_name,
            primary_upload_time=fact.file.create_time,
        )

    async def _search(self, knowledge_id, keyword, current_file_id, *, source_only=False, page_size=None, cursor=None):
        if page_size is not None and (type(page_size) is not int or not 1 <= page_size <= 200):
            raise ValueError("candidate page sizes contain 1..200 rows")
        anchor, context = await self._anchor(current_file_id, knowledge_id)
        keyword = (keyword or "").strip().lower()
        signature = self._cursor_context(context, knowledge_id, current_file_id, keyword, source_only, page_size)
        try:
            key = decode_cursor(cursor, expected_key_len=1, expected_context=signature)
            after = key[0] if key is not None else None
            if after is not None:
                self.repository._id(after)
        except (ValueError, TypeError, AttributeError, KeyError) as error:
            raise KnowledgeSpaceInvalidCursorError() from error
        items, consumed, last = [], 0, after

        def result(more):
            return VersionCandidatePage(
                data=items,
                page_size=page_size or 40,
                has_more=more,
                next_cursor=encode_cursor([last], context=signature) if more else None,
            )

        while True:
            limit = min(100, 1000 - consumed) if page_size is not None else 100
            batch = await self.repository.alist_candidates(
                tenant_id=context[1], space_id=knowledge_id, after_document_id=after, limit=limit
            )
            eligible = {
                fact.document.id: fact
                for fact in batch.data
                if fact.document.id != anchor.document.id
                and fact.file.status == KnowledgeFileStatus.SUCCESS.value
                and (not source_only or fact.version_count == 1)
                and (
                    not keyword
                    or keyword in " ".join([fact.file.file_name or "", fact.file.file_encoding or ""]).lower()
                )
            }
            visible = await self._visible(anchor, [fact.file for fact in eligible.values()], context)
            for fact in batch.data:
                if page_size is not None and len(items) == page_size:
                    return result(True)
                consumed += 1
                last = fact.document.id
                if fact.document.id in eligible and fact.file.id in visible:
                    items.append(self._entry(fact))
            if not batch.has_more:
                return result(False)
            after = batch.next_after
            if page_size is not None and (consumed >= 1000 or len(items) == page_size):
                return result(True)

    async def search_associable_documents(self, knowledge_id, keyword, current_file_id):
        # The original array protocol remains complete; only its SQL batches are bounded.
        return (await self._search(knowledge_id, keyword, current_file_id)).data

    async def search_version_sources(self, knowledge_id, keyword, current_file_id):
        return (await self._search(knowledge_id, keyword, current_file_id, source_only=True)).data

    async def search_candidates_page(
        self, *, knowledge_id, keyword, current_file_id, page_size=40, cursor=None, source_only=False
    ):
        return await self._search(
            knowledge_id, keyword, current_file_id, source_only=source_only, page_size=page_size, cursor=cursor
        )
