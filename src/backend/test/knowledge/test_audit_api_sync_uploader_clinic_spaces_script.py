"""Tests for auditing API-sync files whose uploaders lack a clinic space."""

import asyncio
from types import SimpleNamespace

import scripts.audit_api_sync_uploader_clinic_spaces as script_mod
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
)


def _clinic_scope() -> SimpleNamespace:
    return SimpleNamespace(level=KnowledgeSpaceLevelEnum.TEAM_KS, owner_type=KnowledgeSpaceOwnerTypeEnum.USER)


def _department_scope() -> SimpleNamespace:
    return SimpleNamespace(level=KnowledgeSpaceLevelEnum.DEPARTMENT, owner_type="department")


def _file(
    file_id: int,
    *,
    user_id: int | None = 11,
    original_uploader_id: int | None = None,
    user_name: str | None = "zhangsan",
    user_metadata: dict | None = None,
    file_type: int = FileType.FILE.value,
) -> KnowledgeFile:
    return KnowledgeFile(
        id=file_id,
        knowledge_id=10,
        file_name=f"doc-{file_id}.pdf",
        file_type=file_type,
        user_id=user_id,
        user_name=user_name,
        original_uploader_id=original_uploader_id,
        user_metadata=user_metadata or {},
    )


def test_is_api_sync_file_matches_filelib_metadata() -> None:
    assert script_mod.is_api_sync_file(_file(1, user_metadata={"filelib_sync_endpoint": "inspection_standard_sync"}))
    assert script_mod.is_api_sync_file(_file(2, user_metadata={"external_file_id": "EXT-1"}))
    assert not script_mod.is_api_sync_file(_file(3, user_metadata={}))
    assert not script_mod.is_api_sync_file(
        _file(4, file_type=FileType.DIR.value, user_metadata={"external_file_id": "EXT-1"})
    )


def test_resolve_uploader_id_prefers_original_uploader() -> None:
    assert script_mod.resolve_uploader_id(_file(1, user_id=11, original_uploader_id=22)) == 22
    assert script_mod.resolve_uploader_id(_file(2, user_id=11, original_uploader_id=None)) == 11
    assert script_mod.resolve_uploader_id(_file(3, user_id=None, original_uploader_id=None)) is None


def test_department_chain_ids_walks_self_to_root() -> None:
    department = SimpleNamespace(id=4, path="/1/2/3/4/")
    assert script_mod.department_chain_ids(department) == [4, 3, 2, 1]


def test_build_missing_users_skips_uploaders_with_clinic_space() -> None:
    files = [
        _file(1, user_id=11, user_metadata={"filelib_sync_endpoint": "sync"}),
        _file(2, user_id=12, user_metadata={"external_file_id": "EXT-1"}),
    ]
    users = {
        11: SimpleNamespace(user_id=11, user_name="has-space", delete=0),
        12: SimpleNamespace(user_id=12, user_name="no-space", delete=0),
    }
    memberships = {
        11: [SimpleNamespace(user_id=11, department_id=101, is_primary=1)],
        12: [SimpleNamespace(user_id=12, department_id=202, is_primary=1)],
    }
    departments = {
        101: SimpleNamespace(id=101, name="有库科室", dept_id="D101", path="/1/101/", status="active"),
        202: SimpleNamespace(id=202, name="无库科室", dept_id="D202", path="/1/202/", status="active"),
    }
    bindings = {101: SimpleNamespace(department_id=101, space_id=501)}
    spaces = {501: SimpleNamespace(id=501, name="有库科室知识库")}
    scopes = {501: _clinic_scope()}

    missing = script_mod.build_missing_users(
        files,
        users=users,
        memberships_by_user=memberships,
        departments=departments,
        bindings=bindings,
        spaces=spaces,
        sample_limit=8,
        scopes=scopes,
    )

    assert [item.user_id for item in missing] == [12]
    assert missing[0].reason == "no_clinic_space"
    assert missing[0].departments[0].name == "无库科室"
    assert missing[0].departments[0].clinic_space_id is None


def test_build_missing_users_records_users_without_department() -> None:
    files = [_file(1, user_id=33, user_name="orphan", user_metadata={"external_file_id": "EXT-2"})]
    missing = script_mod.build_missing_users(
        files,
        users={33: SimpleNamespace(user_id=33, user_name="orphan", delete=0)},
        memberships_by_user={},
        departments={},
        bindings={},
        spaces={},
        sample_limit=8,
    )

    assert len(missing) == 1
    assert missing[0].reason == "no_department"
    assert missing[0].departments == []
    assert missing[0].file_count == 1


def test_build_missing_users_records_missing_user_and_sync_department() -> None:
    files = [
        _file(
            1,
            user_id=44,
            user_name="ghost",
            user_metadata={
                "filelib_sync_endpoint": "sync",
                "department_id": 9,
                "department": "同步科室",
            },
        )
    ]
    missing = script_mod.build_missing_users(
        files,
        users={},
        memberships_by_user={},
        departments={},
        bindings={},
        spaces={},
        sample_limit=8,
    )

    assert missing[0].user_id == 44
    assert missing[0].user_name == "ghost"
    assert missing[0].user_exists is False
    assert missing[0].reason == "user_not_found"
    assert missing[0].sync_departments[0].department_id == 9
    assert missing[0].sync_departments[0].name == "同步科室"


def test_build_missing_users_skips_when_ancestor_has_clinic_space() -> None:
    files = [_file(1, user_id=11, user_metadata={"filelib_sync_endpoint": "sync"})]
    missing = script_mod.build_missing_users(
        files,
        users={11: SimpleNamespace(user_id=11, user_name="squad-user", delete=0)},
        memberships_by_user={11: [SimpleNamespace(user_id=11, department_id=4, is_primary=1)]},
        departments={
            4: SimpleNamespace(id=4, name="班组", dept_id="D4", path="/1/3/4/", status="active"),
            3: SimpleNamespace(id=3, name="科室", dept_id="D3", path="/1/3/", status="active"),
            1: SimpleNamespace(id=1, name="公司", dept_id="D1", path="/1/", status="active"),
        },
        bindings={3: SimpleNamespace(department_id=3, space_id=501)},
        spaces={501: SimpleNamespace(id=501, name="科室知识库")},
        sample_limit=8,
        scopes={501: _clinic_scope()},
    )
    assert missing == []


def test_build_missing_users_ignores_department_library_binding() -> None:
    files = [_file(1, user_id=11, user_metadata={"filelib_sync_endpoint": "sync"})]
    missing = script_mod.build_missing_users(
        files,
        users={11: SimpleNamespace(user_id=11, user_name="dept-user", delete=0)},
        memberships_by_user={11: [SimpleNamespace(user_id=11, department_id=2, is_primary=1)]},
        departments={
            2: SimpleNamespace(id=2, name="部门", dept_id="D2", path="/1/2/", status="active"),
        },
        bindings={2: SimpleNamespace(department_id=2, space_id=601)},
        spaces={601: SimpleNamespace(id=601, name="部门知识库")},
        sample_limit=8,
        scopes={601: _department_scope()},
    )
    assert [item.user_id for item in missing] == [11]
    assert missing[0].reason == "no_clinic_space"
    assert missing[0].departments[0].clinic_space_id is None


def test_close_resources_disposes_database_before_loop_exit(monkeypatch) -> None:
    closed = {"db": False, "app": False}

    class _Conn:
        async def close(self):
            closed["db"] = True

    async def fake_get_database_connection():
        return _Conn()

    async def fake_close_app_context():
        closed["app"] = True

    monkeypatch.setattr(script_mod, "get_database_connection", fake_get_database_connection)
    monkeypatch.setattr(script_mod, "close_app_context", fake_close_app_context)
    asyncio.run(script_mod.close_resources())
    assert closed["db"] is True
    assert closed["app"] is True
