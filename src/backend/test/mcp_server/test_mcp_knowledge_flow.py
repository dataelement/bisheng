"""Real SDK, domain services and SQLite with controlled authorization/storage/worker ports."""

import importlib
import io
from contextlib import asynccontextmanager
from functools import partial
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge_space import SpaceFileDuplicateError
from bisheng.core.context.tenant import current_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_mcp_repository_impl import (
    KnowledgeMcpRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_mcp_ingestion_service import KnowledgeMcpIngestionService
from test.knowledge.test_mcp_knowledge_content_service import real_utilities  # noqa: F401
from test.knowledge.test_mcp_knowledge_repository import repository  # noqa: F401
from test.mcp_server.test_mcp_server import server, session


class ResponseBytes(io.BytesIO):
    def release_conn(self):
        self.close()


class StoragePort:
    bucket = "public"
    tmp_bucket = "tmp"

    def __init__(self):
        self.objects = {"preview/1.txt": b"policy content"}
        self.staged = {}
        self.names = {}

    async def stage_name(self, name):
        key = uuid4().hex + "." + name.rsplit(".", 1)[-1]
        self.names[key] = name
        return key

    async def put_object_tmp(self, *, object_name, file):
        self.staged[object_name] = file

    async def get_share_link(self, object_name, bucket, **kwargs):
        return "https://example.test/" + object_name

    async def remove_object(self, bucket, object_name):
        self.staged.pop(object_name, None)

    async def object_exists(self, bucket, object_name):
        return object_name in self.objects

    def download_object_sync(self, bucket, object_name):
        return ResponseBytes(self.objects[object_name])


class OwnerPort:
    def __init__(self, db, user, storage):
        self.db, self.login_user, self.storage = db, user, storage
        self.doc_repo = KnowledgeDocumentRepositoryImpl(db)
        self.version_repo = KnowledgeDocumentVersionRepositoryImpl(db)
        self.knowledge_file_repo = KnowledgeMcpRepositoryImpl(db)

    async def _get_effective_permission_ids(self, *args, **kwargs):
        return {"view_space", "view_folder", "view_file", "upload_file_to_space", "upload_file_to_folder"}

    async def get_existing_portal_visible_space_levels(self):
        return {118: "team"}

    async def get_file_preview(self, file_id):
        file = await self.db.get(KnowledgeFile, file_id)
        return {
            "preview_url": await self.storage.get_share_link(file.preview_file_object_name, self.storage.bucket),
            "original_url": "",
        }

    async def add_file(self, *, knowledge_id, parent_id, file_path, **kwargs):
        key = file_path[0].rsplit("/", 1)[-1]
        name = self.storage.names[key]
        existing = (
            await self.db.exec(
                select(KnowledgeFile).where(
                    KnowledgeFile.knowledge_id == knowledge_id,
                    KnowledgeFile.file_name == name,
                )
            )
        ).first()
        if existing:
            raise SpaceFileDuplicateError()
        row = KnowledgeFile(
            tenant_id=7,
            knowledge_id=knowledge_id,
            user_id=7,
            file_name=name,
            file_type=1,
            file_size=len(self.storage.staged[key]),
            file_level_path=f"/{parent_id}" if parent_id else "",
            status=5,
        )
        self.db.add(row)
        await self.db.flush()
        row.preview_file_object_name = f"preview/{row.id}.txt"
        self.storage.objects[row.preview_file_object_name] = self.storage.staged[key]
        self.db.add(
            KnowledgeDocument(
                id=row.id + 10000, tenant_id=7, knowledge_id=knowledge_id, primary_version_id=row.id + 20000
            )
        )
        self.db.add(
            KnowledgeDocumentVersion(
                id=row.id + 20000, document_id=row.id + 10000, knowledge_file_id=row.id, version_no=1, is_primary=True
            )
        )
        await self.db.commit()
        return [row]

    def get_preview_cache_key(self, *args):
        return "e2e-mcp-preview"

    async def enqueue_file_title_extraction(self, files, keys, **kwargs):
        assert kwargs["operator_user_id"] == 7
        assert current_tenant_id.get() == 7


async def test_nine_tools_sdk_flow_uses_real_services_and_repositories(monkeypatch, repository):  # noqa: F811
    """AC-03-12, AC-14, AC-16-18: browse/read/write/read-back plus tenant denial."""
    token = current_tenant_id.set(7)
    try:
        db = repository.session
        db.add(Knowledge(id=118, tenant_id=7, name="e2e-mcp-space", type=3, user_id=7))
        db.add(
            KnowledgeFile(
                id=305,
                tenant_id=7,
                knowledge_id=118,
                user_id=7,
                file_type=0,
                file_name="e2e-folder",
                file_level_path="",
                status=2,
            )
        )
        db.add(
            KnowledgeFile(
                id=1,
                tenant_id=7,
                knowledge_id=118,
                user_id=7,
                file_type=1,
                file_name="policy.txt",
                file_level_path="",
                status=2,
                preview_file_object_name="preview/1.txt",
            )
        )
        db.add(KnowledgeDocument(id=200, tenant_id=7, knowledge_id=118, primary_version_id=300))
        db.add(KnowledgeDocumentVersion(id=300, document_id=200, knowledge_file_id=1, version_no=1, is_primary=True))
        await db.commit()
        factory = importlib.import_module("bisheng.mcp_server.domain.services.factory")
        storage, active = StoragePort(), []

        @asynccontextmanager
        async def session_scope():
            async with AsyncSession(db.bind, expire_on_commit=False) as scoped:
                active.append(scoped)
                try:
                    yield scoped
                finally:
                    active.remove(scoped)

        monkeypatch.setattr(factory, "get_async_db_session", session_scope)
        monkeypatch.setattr(factory, "get_minio_storage", AsyncMock(return_value=storage))
        monkeypatch.setattr(
            factory,
            "build_knowledge_space_service_for_filelib_sync",
            lambda *, session, login_user, **kwargs: OwnerPort(session, login_user, storage),
        )
        monkeypatch.setattr(
            factory,
            "KnowledgeMcpIngestionService",
            partial(
                KnowledgeMcpIngestionService,
                size_validator=lambda *args: None,
                name_factory=storage.stage_name,
            ),
        )
        monkeypatch.setattr(KnowledgeMcpRepositoryImpl, "content_matches", AsyncMock(return_value={1}))
        async with server(monkeypatch) as (app, _, _):
            async with session(app) as client:

                async def call(name, **args):
                    result = await client.call_tool(name, args)
                    assert not result.isError, str(result)
                    return result.structuredContent

                spaces = await call("list_knowledge", writable_only=True)
                assert spaces["data"][0]["id"] == 118
                folders = await call("list_folders", knowledge_id=118)
                assert folders["data"][0]["id"] == 305
                files = await call("list_files", knowledge_id=118)
                assert [r["id"] for r in files["data"]] == [1]
                found = await call("search_files", keyword="policy", knowledge_ids=[118])
                assert found["data"][0]["id"] == 1
                detail = await call("get_file_detail", knowledge_id=118, file_id=1)
                assert detail["content"] == "policy content"
                source = await call("get_file_source", knowledge_id=118, file_id=1)
                assert source["preview_url"] and not source["original_url"]
                retrieved = await call(
                    "retrieve_chunks",
                    query="policy",
                    knowledge_base_ids=[118],
                    filters={"knowledge_base_filters": [{"knowledge_base_id": 118, "tags": ["policy"]}]},
                )
                assert retrieved["total"] == 1
                created = await call(
                    "create_document", knowledge_id=118, folder_id=305, file_name="e2e-note.md", content="# note"
                )
                uploaded = await call(
                    "upload_file", knowledge_id=118, file_name="e2e-upload.txt", content_base64="aGVsbG8="
                )
                assert created["accepted"] and uploaded["accepted"]
                waiting = await call("get_file_detail", knowledge_id=118, file_id=created["file_id"])
                assert waiting["file"]["status"] == 5 and not waiting["content_ready"]
                duplicate = await client.call_tool(
                    "create_document",
                    {
                        "knowledge_id": 118,
                        "folder_id": 305,
                        "file_name": "e2e-note.md",
                        "content": "changed",
                    },
                )
                assert duplicate.isError
                async with AsyncSession(db.bind) as worker:
                    row = await worker.get(KnowledgeFile, created["file_id"])
                    row.status = 2
                    await worker.commit()
                ready = await call("get_file_detail", knowledge_id=118, file_id=created["file_id"])
                assert ready["content"] == "# note" and ready["content_ready"]
                listed = await call("list_files", knowledge_id=118, folder_id=305)
                assert [r["id"] for r in listed["data"]] == [created["file_id"]]
            async with session(app, token="second") as other:
                denied = await other.call_tool("get_file_detail", {"knowledge_id": 118, "file_id": 1})
                assert denied.isError and "policy" not in str(denied)
        assert not active and not storage.staged
    finally:
        current_tenant_id.reset(token)
