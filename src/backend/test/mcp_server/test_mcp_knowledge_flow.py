"""Real SDK, domain services and SQLite with controlled authorization/storage/worker ports."""

import importlib
import io
from contextlib import asynccontextmanager
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from langchain_core.documents import Document
from sqlalchemy import DefaultClause, MetaData, text
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import SpaceFileDuplicateError
from bisheng.core.context.tenant import current_tenant_id
from bisheng.database.models.tenant import Tenant, UserTenant
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
from bisheng.user.domain.repositories.implementations import user_repository_impl
from test.knowledge.test_mcp_knowledge_content_service import real_utilities  # noqa: F401
from test.knowledge.test_mcp_knowledge_repository import repository  # noqa: F401
from test.mcp_server.test_mcp_server import server, session


class IdentityUserFixture(SQLModel, table=True):
    # 全局 User import 预桩存在时。用真实映射表运行原 UserRepository 查询。
    __tablename__ = "f081_mcp_user_fixture"
    user_id: int | None = Field(default=None, primary_key=True)
    external_id: str
    user_name: str
    source: str = "e2e"
    delete: int = 0
    token_version: int = 0


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
        if self.login_user.user_id == 9 or (args[0] == "knowledge_file" and args[1] == 903):
            return set()
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
            tenant_id=self.login_user.tenant_id,
            knowledge_id=knowledge_id,
            user_id=self.login_user.user_id,
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
                id=row.id + 10000,
                tenant_id=self.login_user.tenant_id,
                knowledge_id=knowledge_id,
                primary_version_id=row.id + 20000,
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
        assert kwargs["operator_user_id"] == self.login_user.user_id == 7
        assert current_tenant_id.get() == self.login_user.tenant_id == 7
        assert all(file.user_id == self.login_user.user_id and file.tenant_id == 7 for file in files)


async def test_nine_tools_sdk_flow_uses_real_services_and_repositories(monkeypatch, repository):  # noqa: F811
    """AC-03-12, AC-14, AC-16-18: browse/read/write/read-back plus tenant denial."""
    token = current_tenant_id.set(7)
    try:
        db = repository.session
        metadata = MetaData()
        for model in (IdentityUserFixture, Tenant, UserTenant):
            table = model.__table__.to_metadata(metadata)
            for column in table.columns:
                if column.server_default is not None and "ON UPDATE" in str(column.server_default.arg):
                    column.server_default = DefaultClause(text("CURRENT_TIMESTAMP"))
        async with db.bind.begin() as connection:
            await connection.run_sync(metadata.create_all)
        for user_id, tenant_id in [(7, 7), (8, 8), (9, 7)]:
            db.add(
                IdentityUserFixture(user_id=user_id, user_name=f"e2e-mcp-user-{user_id}", external_id=f"000{user_id}")
            )
            db.add(UserTenant(user_id=user_id, tenant_id=tenant_id, is_active=1, status="active"))
        for tenant_id in [7, 8]:
            db.add(Tenant(id=tenant_id, tenant_code=f"e2e-mcp-{tenant_id}", tenant_name=f"e2e-mcp-{tenant_id}"))
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
        for file_id, kind, path in [
            (400, 0, "/305"),
            (401, 0, "/305"),
            (901, 1, "/305"),
            (902, 1, "/305/400"),
            (903, 1, "/305"),
            (904, 1, "/3050"),
        ]:
            db.add(
                KnowledgeFile(
                    id=file_id,
                    knowledge_id=118,
                    tenant_id=7,
                    user_id=7,
                    file_type=kind,
                    file_name=f"scope-{file_id}.txt",
                    file_level_path=path,
                    status=2,
                )
            )
        await db.commit()
        factory = importlib.import_module("bisheng.mcp_server.domain.services.factory")
        monkeypatch.setattr(user_repository_impl, "User", IdentityUserFixture)
        storage, active = StoragePort(), []

        async def login_user(**kwargs):
            return UserPayload(user_role=[2], **kwargs)

        monkeypatch.setattr(UserPayload, "init_login_user", login_user)
        monkeypatch.setattr(factory.settings, "multi_tenant", type("Mode", (), {"enabled": True})())

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
        folder_scopes = []

        @asynccontextmanager
        async def folder_search_factory(request, user):
            from bisheng.open_endpoints.domain.services.filelib_retrieve_service import FilelibRetrieveService

            async def retrieve_backend(**kwargs):
                assert user.user_id == user.tenant_id == current_tenant_id.get() == 7
                assert kwargs["strict_file_scope"] is True
                ids = kwargs["kb_filters"][118]["file_ids"]
                folder_scopes.append(ids)
                return [
                    (
                        118,
                        Document(
                            page_content="scoped policy",
                            metadata={
                                "document_id": file_id,
                                "document_name": f"scope-{file_id}.txt",
                            },
                        ),
                    )
                    for file_id in ids
                ]

            yield FilelibRetrieveService(
                SimpleNamespace(aretrieve_chunks=retrieve_backend),
                SimpleNamespace(resolve_links=AsyncMock(return_value={})),
                SimpleNamespace(config=SimpleNamespace(total_timeout_seconds=1, source_link_timeout_seconds=1)),
            )

        async with server(monkeypatch, identity_resolver=factory.resolve_execution_identity) as (app, calls, _):
            async with session(app, token="second") as client:

                async def call(name, **args):
                    result = await client.call_tool(name, {"external_id": "0007", **args})
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
                legacy = await call("search_knowledge", query="policy", knowledge_base_ids=[118])
                assert legacy["total"] == 1 and calls[-1][:2] == (7, 7)
                base_factory = app.routes[0].endpoint.tool_runtime.factory
                app.routes[0].endpoint.tool_runtime.factory = partial(
                    factory.build_tool_services,
                    search_factory=folder_search_factory,
                )
                scoped = await call("retrieve_folder_chunks", query="policy", knowledge_id=118, folder_id="000305")
                assert {chunk["document_id"] for chunk in scoped["chunks"]} == {901, 902}
                direct = await call(
                    "retrieve_folder_chunks",
                    query="policy",
                    knowledge_id=118,
                    folder_id=305,
                    recursive=False,
                )
                assert [chunk["document_id"] for chunk in direct["chunks"]] == [901]
                empty = await call("retrieve_folder_chunks", query="policy", knowledge_id=118, folder_id=401)
                assert empty == {"chunks": [], "total": 0}
                assert folder_scopes == [[901, 902], [901]]
                app.routes[0].endpoint.tool_runtime.factory = base_factory
                created = await call(
                    "create_document", knowledge_id=118, folder_id=305, file_name="e2e-note.md", content="# note"
                )
                uploaded = await call(
                    "upload_file", knowledge_id=118, file_name="e2e-upload.txt", content_base64="aGVsbG8="
                )
                assert created["accepted"] and uploaded["accepted"]
                async with AsyncSession(db.bind) as check:
                    for saved in [created, uploaded]:
                        row = await check.get(KnowledgeFile, saved["file_id"])
                        assert (row.user_id, row.tenant_id) == (7, 7)
                waiting = await call("get_file_detail", knowledge_id=118, file_id=created["file_id"])
                assert waiting["file"]["status"] == 5 and not waiting["content_ready"]
                duplicate = await client.call_tool(
                    "create_document",
                    {
                        "external_id": "0007",
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
                assert {r["id"] for r in listed["data"]} == {created["file_id"], 901}
            async with session(app, token="first") as other:
                denied = await other.call_tool(
                    "get_file_detail", {"external_id": "0008", "knowledge_id": 118, "file_id": 1}
                )
                assert denied.isError and "policy" not in str(denied)
                cross_tenant_folder = await other.call_tool(
                    "retrieve_folder_chunks",
                    {
                        "external_id": "0008",
                        "query": "policy",
                        "knowledge_id": 118,
                        "folder_id": 305,
                    },
                )
                assert cross_tenant_folder.isError and "scoped policy" not in str(cross_tenant_folder)
                for name, args in [
                    ("get_file_detail", {"knowledge_id": 118, "file_id": 1}),
                    ("retrieve_folder_chunks", {"query": "policy", "knowledge_id": 118, "folder_id": 305}),
                    ("create_document", {"knowledge_id": 118, "file_name": "e2e-denied.md", "content": "denied"}),
                    ("upload_file", {"knowledge_id": 118, "file_name": "e2e-denied.txt", "content_base64": "YQ=="}),
                ]:
                    result = await other.call_tool(name, {"external_id": "0009", **args})
                    assert result.isError
        assert not active and not storage.staged
    finally:
        current_tenant_id.reset(token)
