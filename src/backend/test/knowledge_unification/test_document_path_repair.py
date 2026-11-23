"""Legacy path repair is explicit, frozen, single-version and permission-confirmed."""

import json
import stat

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Doc
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.permission.domain.models import ResourcePermissionMode as Mode
from scripts.repair_knowledge_document_path import repair
from test.knowledge_unification.test_job_repo import job_tenant as job_tenant


@pytest.fixture
async def store(job_tenant):
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    models = (
        Knowledge,
        File,
        Doc,
        Version,
        Mode,
        KnowledgeOperationPlan,
        KnowledgeProcessingJob,
        KnowledgeProcessingItem,
    )
    async with engine.begin() as connection:
        await connection.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=[m.__table__ for m in models]))
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all(
            [
                Knowledge(id=10, tenant_id=101, type=3, state=1, user_id=7, name="Source"),
                File(
                    id=50, tenant_id=101, knowledge_id=10, file_name="Folder", file_type=0, file_level_path="", level=0
                ),
                File(
                    id=81,
                    tenant_id=101,
                    knowledge_id=10,
                    file_name="File",
                    file_type=1,
                    file_level_path="/50",
                    level=1,
                    status=2,
                ),
                Doc(id=80, knowledge_id=10, file_level_path="", level=0, primary_version_id=91),
                Version(id=91, document_id=80, knowledge_file_id=81, version_no=1, is_primary=True),
                Mode(
                    id=1,
                    tenant_id=101,
                    resource_type="knowledge_file",
                    resource_id="81",
                    mode="INHERIT",
                    parent_type="folder",
                    parent_id="50",
                    projection_state="CURRENT",
                    version=1,
                ),
            ]
        )
        await session.commit()
        yield session
    await engine.dispose()


async def test_preview_then_frozen_apply_preserves_file_and_permission_parent(store, tmp_path):
    before = await repair(store, tenant_id=101, space_id=10, file_id=81)
    assert (await store.get(Doc, 80)).file_level_path == ""
    backup = tmp_path / "before.json"
    result = await repair(
        store, tenant_id=101, space_id=10, file_id=81, apply=True, expected_digest=before["digest"], backup=backup
    )
    await store.commit()
    assert result["applied"] and (await store.get(Doc, 80)).file_level_path == "/50"
    assert (await store.get(Doc, 80)).level == 1
    assert (await store.get(File, 81)).file_level_path == "/50"
    assert (await store.get(Mode, 1)).parent_id == "50"
    assert json.loads(backup.read_text())["facts"]["document"]["path"] == ""
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


async def test_changed_preview_does_not_write_or_create_backup(store, tmp_path):
    before = await repair(store, tenant_id=101, space_id=10, file_id=81)
    (await store.get(Mode, 1)).version += 1
    await store.commit()
    backup = tmp_path / "before.json"
    with pytest.raises(ValueError, match="unchanged preview"):
        await repair(
            store, tenant_id=101, space_id=10, file_id=81, apply=True, expected_digest=before["digest"], backup=backup
        )
    assert not backup.exists() and (await store.get(Doc, 80)).file_level_path == ""


@pytest.mark.parametrize("case", ["multiple_versions", "permission_parent", "tenant", "folder_chain"])
async def test_ambiguous_or_unconfirmed_path_is_rejected(store, case):
    if case == "multiple_versions":
        store.add(Version(id=92, document_id=80, knowledge_file_id=82, version_no=2, is_primary=False))
    elif case == "permission_parent":
        (await store.get(Mode, 1)).parent_id = "99"
    elif case == "tenant":
        (await store.get(File, 81)).tenant_id = 202
    else:
        (await store.get(File, 50)).file_type = 1
    await store.commit()
    with pytest.raises(ValueError):
        await repair(store, tenant_id=101, space_id=10, file_id=81)
    assert (await store.get(Doc, 80)).file_level_path == ""
