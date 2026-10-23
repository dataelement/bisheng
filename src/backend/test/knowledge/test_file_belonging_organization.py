"""文件所属组织的真实仓储及发布事务回归。"""

import importlib
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import mysql
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.schema import CreateColumn
from sqlmodel import select

from bisheng.database.models.department import Department, UserDepartment
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
from bisheng.knowledge.domain.services.knowledge_document_distribution_service import PublishKnowledgeDocumentCommand
from bisheng.knowledge.domain.services.knowledge_file_organization_service import KnowledgeFileOrganizationService
from test.knowledge.test_knowledge_document_distribution_publish import _seed_manager, _service

_GROUP_MODEL = None


@pytest.fixture(autouse=True)
async def current_organization_schema(async_db_session, monkeypatch):
    global _GROUP_MODEL
    connection = await async_db_session.connection()
    await connection.run_sync(lambda sync: Department.__table__.drop(sync))
    await connection.run_sync(lambda sync: Department.__table__.create(sync))
    await connection.run_sync(lambda sync: DepartmentKnowledgeSpace.__table__.create(sync, checkfirst=True))
    await connection.execute(
        sa.text("ALTER TABLE knowledge_space_scope ADD COLUMN portal_discovery_enabled BOOLEAN NOT NULL DEFAULT 0")
    )
    # 公共夹具会预先替换团队模块, 仅在本模块的仓储边界恢复真实模型。
    from sqlmodel import SQLModel

    import bisheng.knowledge.domain.repositories.implementations.knowledge_file_organization_repository_impl as repo

    if _GROUP_MODEL is None and "group" not in SQLModel.metadata.tables:
        path = Path(__file__).parents[2] / "bisheng/database/models/group.py"
        spec = importlib.util.spec_from_file_location("_file_org_real_group", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _GROUP_MODEL = module.Group
    elif _GROUP_MODEL is None:
        _GROUP_MODEL = next(
            mapper.class_ for mapper in Department._sa_registry.mappers if mapper.local_table.name == "group"
        )
    monkeypatch.setattr(repo, "Group", _GROUP_MODEL)


def test_nullable_migration_keeps_historical_rows(monkeypatch):
    migration = importlib.import_module(
        "bisheng.core.database.alembic.versions.v2_6_0_f118_file_belonging_organization"
    )
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE knowledgefile (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO knowledgefile (id) VALUES (1)"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.upgrade()
        assert connection.execute(sa.text("SELECT belonging_organization_id FROM knowledgefile")).scalar_one() is None
        migration.downgrade()
        assert connection.execute(sa.text("SELECT id FROM knowledgefile")).scalar_one() == 1
    dm = DefaultDialect()
    dm.name = "dm"
    for dialect in (mysql.dialect(), dm):
        column = KnowledgeFile.__table__.c.belonging_organization_id
        assert "INTEGER" in str(CreateColumn(column).compile(dialect=dialect))
        assert column.nullable and column.server_default is None


@pytest.mark.parametrize(
    "case,expected",
    [("one", 81), ("none", None), ("multiple", None), ("secondary", None), ("archived", None), ("foreign", None)],
)
async def test_unique_primary_organization(async_db_session, case, expected):
    session = async_db_session
    session.add_all(
        [
            Department(
                id=81, dept_id="org81", name="科室", tenant_id=7, status="archived" if case == "archived" else "active"
            ),
            Department(id=82, dept_id="org82", name="其他", tenant_id=8 if case == "foreign" else 7),
        ]
    )
    if case != "none":
        await session.execute(
            sa.insert(UserDepartment.__table__).values(
                user_id=501, department_id=82 if case == "foreign" else 81, is_primary=0 if case == "secondary" else 1
            )
        )
    if case == "multiple":
        await session.execute(sa.insert(UserDepartment.__table__).values(user_id=501, department_id=82, is_primary=1))
    await session.commit()
    assert await KnowledgeFileOrganizationService(session).for_uploader(501, tenant_id=7) == expected
    from bisheng.knowledge.domain.repositories.implementations.knowledge_file_organization_repository_impl import (
        KnowledgeFileOrganizationRepositoryImpl,
    )

    assert (
        await session.run_sync(
            lambda sync: KnowledgeFileOrganizationRepositoryImpl(sync).primary_organization_sync(501, 7)
        )
        == expected
    )


async def seed_publish_organization(session, target="clinic"):
    await _seed_manager(session)
    clinic = target in {"clinic", "portal_clinic"}
    portal = target.startswith("portal_")
    session.add_all(
        [
            Department(id=81, dept_id="org81", name="目标科室", tenant_id=7),
            KnowledgeSpaceScope(space_id=10, tenant_id=7, level="personal", owner_type="user", owner_id=501),
            KnowledgeSpaceScope(
                space_id=20,
                tenant_id=7,
                level="team_ks" if clinic else "team",
                owner_type="user" if portal else "department" if clinic else "user_group",
                owner_id=601 if portal else 81 if clinic else 71,
                created_by=601,
            ),
            KnowledgeFile(
                id=102,
                tenant_id=7,
                knowledge_id=30,
                file_name="shared.pdf",
                status=2,
                reference_document_id=91,
                entry_type="share",
                entry_status="active",
            ),
        ]
    )
    if clinic:
        session.add(DepartmentKnowledgeSpace(space_id=20, department_id=81, tenant_id=7))
    await session.execute(sa.insert(UserDepartment.__table__).values(user_id=601, department_id=81, is_primary=1))
    from sqlmodel import SQLModel

    await session.execute(
        sa.insert(SQLModel.metadata.tables["group"]).values(id=71, group_name="团队", tenant_id=7, create_user=601)
    )
    await session.commit()


@pytest.mark.parametrize("target", ["clinic", "team", "portal_clinic", "portal_team"])
async def test_publish_updates_all_versions_and_entries_only_on_success(async_db_session, target):
    session = async_db_session
    await seed_publish_organization(session, target)
    svc = _service(session, tuple_writer=AsyncMock())
    command = PublishKnowledgeDocumentCommand(
        tenant_id=7, approval_instance_id=301, document_id=91, source_entry_id=100, target_space_id=20
    )
    await svc._prepare_publish_entry(command)
    rows = (await session.exec(select(KnowledgeFile))).all()
    assert all(row.belonging_organization_id is None for row in rows)

    result = await svc.publish_approved(command)
    rows = (await session.exec(select(KnowledgeFile).execution_options(populate_existing=True))).all()
    assert len(rows) == 4
    assert {row.belonging_organization_id for row in rows} == {81}
    assert (await svc.publish_approved(command)).idempotent
    assert result.target_space_id == 20


@pytest.mark.parametrize("scenario", ["no_primary", "not_personal", "department_target", "legacy_clinic"])
async def test_publish_organization_boundaries(async_db_session, scenario):
    session = async_db_session
    await seed_publish_organization(session, "clinic" if scenario == "legacy_clinic" else "team")
    files = (await session.exec(select(KnowledgeFile))).all()
    for file in files:
        file.belonging_organization_id = 88
    source = (await session.exec(select(KnowledgeSpaceScope).where(KnowledgeSpaceScope.space_id == 10))).one()
    target = (await session.exec(select(KnowledgeSpaceScope).where(KnowledgeSpaceScope.space_id == 20))).one()
    if scenario == "no_primary":
        await session.execute(sa.delete(UserDepartment.__table__))
    elif scenario == "not_personal":
        source.level = "department"
        session.add(source)
    elif scenario == "department_target":
        target.level = "department"
        session.add(target)
    else:
        target.level = "team"
        session.add(target)
    await session.commit()
    await KnowledgeFileOrganizationService(session).apply_publish(
        document_id=91, source_space_id=10, target_space_id=20, tenant_id=7
    )
    await session.commit()
    expected = None if scenario == "no_primary" else 81 if scenario == "legacy_clinic" else 88
    assert {row.belonging_organization_id for row in (await session.exec(select(KnowledgeFile))).all()} == {expected}


async def test_publish_merge_updates_the_final_document(async_db_session):
    session = async_db_session
    await seed_publish_organization(session)
    await session.delete(await session.get(KnowledgeDocumentVersion, 500))
    await session.delete(await session.get(KnowledgeFile, 99))
    session.add_all(
        [
            KnowledgeDocument(id=92, tenant_id=7, knowledge_id=20, primary_version_id=601),
            KnowledgeFile(
                id=200, tenant_id=7, knowledge_id=20, file_name="target.pdf", status=2, belonging_organization_id=88
            ),
            KnowledgeDocumentVersion(id=601, document_id=92, knowledge_file_id=200, version_no=1, is_primary=True),
        ]
    )
    await session.commit()
    result = await _service(session, tuple_writer=AsyncMock()).publish_approved(
        PublishKnowledgeDocumentCommand(
            tenant_id=7,
            approval_instance_id=301,
            document_id=91,
            source_entry_id=100,
            target_space_id=20,
            target_document_id=92,
        )
    )
    assert result.document_id == 92
    rows = (await session.exec(select(KnowledgeFile))).all()
    assert {row.belonging_organization_id for row in rows} == {81}


def test_correction_replacement_preserves_document_organization():
    from bisheng.knowledge.domain.services.knowledge_file_correction_update import _copy_file_location

    old = KnowledgeFile(id=1, knowledge_id=10, file_name="old.pdf", belonging_organization_id=81)
    new = KnowledgeFile(id=2, knowledge_id=10, file_name="new.pdf", belonging_organization_id=88)
    _copy_file_location(old, new)
    assert new.belonging_organization_id == 81


async def test_organization_change_rolls_back_with_activation(async_db_session, monkeypatch):
    session = async_db_session
    await seed_publish_organization(session)
    svc = _service(session, tuple_writer=AsyncMock())
    command = PublishKnowledgeDocumentCommand(
        tenant_id=7, approval_instance_id=301, document_id=91, source_entry_id=100, target_space_id=20
    )
    publish = await svc._prepare_publish_entry(command)
    publish_id = publish.id
    monkeypatch.setattr(svc, "_commit", AsyncMock(side_effect=RuntimeError("commit failed")))
    with pytest.raises(RuntimeError, match="commit failed"):
        await svc._activate_publish_transfer(command=command, publish_entry_id=publish_id, source_md5="abc")
    await session.rollback()
    rows = (await session.exec(select(KnowledgeFile))).all()
    assert all(row.belonging_organization_id is None for row in rows)
