"""Tests for moving API-sync files into uploader clinic spaces."""

from types import SimpleNamespace

import scripts.move_api_sync_files_to_uploader_clinic_spaces as script_mod
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus
from scripts.audit_api_sync_uploader_clinic_spaces import (
    DepartmentSnapshot,
    MissingClinicSpaceUser,
)


def _space(space_id: int, name: str, *, model: str = "emb-1", owner_id: int = 9) -> Knowledge:
    return Knowledge(
        id=space_id,
        tenant_id=1,
        user_id=owner_id,
        name=name,
        type=KnowledgeTypeEnum.SPACE.value,
        model=model,
    )


def _file(
    file_id: int,
    *,
    knowledge_id: int = 10,
    file_name: str = "doc.pdf",
    status: int = KnowledgeFileStatus.SUCCESS.value,
    user_id: int = 11,
    file_level_path: str = "",
) -> KnowledgeFile:
    return KnowledgeFile(
        id=file_id,
        knowledge_id=knowledge_id,
        file_name=file_name,
        file_type=FileType.FILE.value,
        status=status,
        user_id=user_id,
        original_uploader_id=user_id,
        user_name="zhangsan",
        file_level_path=file_level_path,
        user_metadata={"filelib_sync_endpoint": "sync"},
    )


def _folder(folder_id: int, name: str, *, path: str = "") -> KnowledgeFile:
    return KnowledgeFile(
        id=folder_id,
        knowledge_id=20,
        file_name=name,
        file_type=FileType.DIR.value,
        file_level_path=path,
        level=0 if path == "" else 1,
        status=KnowledgeFileStatus.SUCCESS.value,
    )


def _uploader(
    user_id: int,
    *,
    reason: str = "has_clinic_space",
    clinic_space_id: int | None = 20,
    clinic_space_name: str | None = "某某科室库",
    department_name: str = "某某科",
    is_primary: bool = True,
) -> MissingClinicSpaceUser:
    departments = []
    if department_name != "-":
        departments.append(
            DepartmentSnapshot(
                department_id=3,
                name=department_name,
                dept_id="D3",
                path="/1/3/",
                status="active",
                is_primary=is_primary,
                clinic_space_id=clinic_space_id,
                clinic_space_name=clinic_space_name,
                clinic_bound_department_id=3,
                clinic_bound_department_name=department_name,
            )
        )
    return MissingClinicSpaceUser(
        user_id=user_id,
        user_name="zhangsan",
        user_exists=True,
        delete=0,
        reason=reason,
        departments=departments,
        file_count=1,
        sample_file_ids=[1],
    )


def _plan(**overrides):
    kwargs = {
        "source_space": _space(10, "安全生产知识库"),
        "folder_path": "安全生产/消防安全",
        "api_sync_files": [_file(1)],
        "uploader_rows": [_uploader(11)],
        "clinic_spaces": {20: _space(20, "某某科室库")},
        "clinic_owners": {9: SimpleNamespace(user_id=9, user_name="owner", delete=0)},
        "clinic_folders": {20: []},
        "clinic_files": {20: []},
    }
    kwargs.update(overrides)
    return script_mod.plan_moves(**kwargs)


def test_target_folder_segments_root_and_nested() -> None:
    assert script_mod.target_folder_segments("/") == []
    assert script_mod.target_folder_segments("安全生产/消防安全") == ["安全生产", "消防安全"]


def test_find_folder_by_segments_walks_nested_path() -> None:
    parent = _folder(5, "安全生产")
    child = _folder(6, "消防安全", path="/5")
    assert script_mod.find_folder_by_segments([parent, child], ["安全生产", "消防安全"]) is child
    assert script_mod.find_folder_by_segments([parent], ["安全生产", "消防安全"]) is None


def test_plan_moves_ready_when_clinic_exists() -> None:
    rows = _plan()
    assert len(rows) == 1
    assert rows[0].status == "ready"
    assert rows[0].reason == "ready"
    assert rows[0].uploader == "zhangsan"
    assert rows[0].department_name == "某某科"
    assert rows[0].clinic_space_name == "某某科室库"
    assert rows[0].target_folder_path == "安全生产/消防安全"
    assert rows[0].folder_action == "create"


def test_plan_moves_reuses_existing_clinic_folder() -> None:
    parent = _folder(5, "安全生产")
    child = _folder(6, "消防安全", path="/5")
    rows = _plan(clinic_folders={20: [parent, child]})
    assert rows[0].status == "ready"
    assert rows[0].folder_action == "reused"


def test_plan_moves_skips_uploaders_without_clinic_space() -> None:
    rows = _plan(uploader_rows=[_uploader(11, reason="no_clinic_space", clinic_space_id=None)])
    assert rows[0].status == "skipped"
    assert rows[0].reason == "no_clinic_space"


def test_plan_moves_allows_failed_and_violation() -> None:
    failed = _plan(api_sync_files=[_file(1, status=KnowledgeFileStatus.FAILED.value)])
    assert failed[0].status == "ready"
    assert failed[0].reason == "ready"

    violation = _plan(api_sync_files=[_file(1, status=KnowledgeFileStatus.VIOLATION.value)])
    assert violation[0].status == "ready"
    assert violation[0].reason == "ready"


def test_plan_moves_skips_in_flight_and_name_conflict() -> None:
    processing = _plan(api_sync_files=[_file(1, status=KnowledgeFileStatus.PROCESSING.value)])
    assert processing[0].reason == "source_not_success:PROCESSING"

    timeout = _plan(api_sync_files=[_file(1, status=KnowledgeFileStatus.TIMEOUT.value)])
    assert timeout[0].reason == "source_not_success:TIMEOUT"

    processing = _file(2, status=KnowledgeFileStatus.PROCESSING.value)
    already = _file(99, knowledge_id=20, file_name="doc.pdf", file_level_path="")
    already.user_id = 11
    already.user_name = "zhangsan"
    processing_but_copied = _plan(
        folder_path="/",
        api_sync_files=[processing],
        clinic_files={20: [already]},
    )
    assert processing_but_copied[0].reason == "already_at_target"

    existing = _file(99, knowledge_id=20, file_name="doc.pdf", file_level_path="")
    existing.user_id = 1
    existing.user_name = "admin"
    existing.reference_document_id = 88
    existing.entry_type = "manager"
    conflict = _plan(
        folder_path="/",
        clinic_files={20: [existing]},
    )
    assert conflict[0].status == "ready"
    assert conflict[0].reason == "repair_target"
    assert conflict[0].target_file_id == 99

    already = _file(99, knowledge_id=20, file_name="doc.pdf", file_level_path="")
    already.user_id = 11
    already.user_name = "zhangsan"
    same_uploader = _plan(
        folder_path="/",
        clinic_files={20: [already]},
    )
    assert same_uploader[0].status == "skipped"
    assert same_uploader[0].reason == "already_at_target"


def test_plan_moves_skips_already_in_clinic_and_model_mismatch() -> None:
    already = _plan(api_sync_files=[_file(1, knowledge_id=20)])
    assert already[0].reason == "already_in_clinic_space"

    mismatch = _plan(clinic_spaces={20: _space(20, "某某科室库", model="other")})
    assert mismatch[0].reason == "embedding_model_mismatch"


def test_plan_moves_skips_batch_name_conflict() -> None:
    rows = _plan(api_sync_files=[_file(1, file_name="same.pdf"), _file(2, user_id=11, file_name="same.pdf")])
    assert rows[0].status == "ready"
    assert rows[1].status == "skipped"
    assert rows[1].reason == "batch_name_conflict"


def test_clinic_move_accepts_failed_and_violation_status() -> None:
    ops = script_mod.ClinicMoveOperations(1, {})
    source_failed = _file(1, status=KnowledgeFileStatus.FAILED.value)
    target_failed = _file(2, status=KnowledgeFileStatus.FAILED.value)
    source_violation = _file(3, status=KnowledgeFileStatus.VIOLATION.value)
    target_violation = _file(4, status=KnowledgeFileStatus.VIOLATION.value)
    source_processing = _file(5, status=KnowledgeFileStatus.PROCESSING.value)
    target_processing = _file(6, status=KnowledgeFileStatus.PROCESSING.value)
    assert ops._accepts_copied_status(source_failed, target_failed) is True
    assert ops._accepts_copied_status(source_violation, target_violation) is True
    assert ops._accepts_copied_status(_file(7), _file(8)) is True
    assert ops._accepts_copied_status(source_failed, _file(9)) is False
    assert ops._accepts_copied_status(source_processing, target_processing) is False


def test_needs_uploader_fix_detects_admin_owner() -> None:
    source = _file(1, user_id=11)
    source.user_name = "刘越"
    target = _file(99, user_id=1)
    target.user_name = "admin"
    assert script_mod.needs_uploader_fix(source, target) is True
    target.user_id = 11
    target.user_name = "刘越"
    assert script_mod.needs_uploader_fix(source, target) is False


def test_collect_leftover_repair_rows_finds_detached_clinic_copies() -> None:
    leftover = _file(77, knowledge_id=20, file_name="old.pdf", file_level_path="")
    leftover.reference_document_id = 88
    leftover.entry_type = "manager"
    extras = script_mod.collect_leftover_repair_rows(
        folder_path="/",
        clinic_spaces={20: _space(20, "某某科室库")},
        clinic_folders={20: []},
        clinic_files={20: [leftover]},
        planned=[],
    )
    assert [row.target_file_id for row in extras] == [77]
    assert extras[0].reason == "repair_target"
    assert extras[0].status == "ready"


def test_standalone_file_values_clear_document_binding() -> None:
    values = script_mod.standalone_file_values()
    assert values["reference_document_id"] is None
    assert values["entry_type"] is None
    assert values["entry_status"] is None


def test_detach_copied_distribution_identity_clears_document_binding() -> None:
    target = _file(99, user_id=1)
    target.reference_document_id = 88
    target.entry_type = "manager"
    target.entry_status = "active"
    script_mod.detach_copied_distribution_identity(target)
    assert target.reference_document_id is None
    assert target.entry_type is None
    assert target.entry_status is None
    assert script_mod.has_copied_distribution_identity(target) is False


def test_plan_moves_repairs_copied_distribution_on_existing_target() -> None:
    existing = _file(99, knowledge_id=20, file_name="doc.pdf", file_level_path="")
    existing.user_id = 11
    existing.user_name = "zhangsan"
    existing.reference_document_id = 88
    existing.entry_type = "manager"
    rows = _plan(folder_path="/", clinic_files={20: [existing]})
    assert rows[0].status == "ready"
    assert rows[0].reason == "repair_target"


def test_preserve_source_uploader_keeps_source_user_not_clinic_owner() -> None:
    source = _file(1, user_id=11)
    source.user_name = "刘辉"
    source.original_uploader_id = 11
    target = _file(99, user_id=1)
    target.user_name = "admin"
    target.original_uploader_id = 11
    script_mod.preserve_source_uploader(source, target)
    assert target.user_id == 11
    assert target.user_name == "刘辉"
    assert target.original_uploader_id == 11


def test_build_clinic_target_context_root_and_folder() -> None:
    space = _space(20, "某某科室库")
    owner = SimpleNamespace(user_id=9, user_name="owner", delete=0)
    root = script_mod.build_clinic_target_context(tenant_id=1, space=space, folder=None, owner=owner)
    assert root.file_level_path == ""
    assert root.level == 0
    assert int(root.folder.id) == 0

    folder = _folder(6, "消防安全", path="/5")
    target = script_mod.build_clinic_target_context(tenant_id=1, space=space, folder=folder, owner=owner)
    assert target.file_level_path == "/5/6"
    assert target.level == 2


def test_print_text_report_shows_uploader_department_and_clinic(capsys) -> None:
    report = script_mod.MoveReport(
        mode="dry-run",
        space_id=10,
        space_name="安全生产知识库",
        folder_path="安全生产/消防安全",
        api_sync_file_count=1,
        ready_count=1,
        skipped_count=0,
        success_count=0,
        failed_count=0,
        rows=[
            script_mod.MoveRow(
                source_file_id=1,
                source_file_name="doc.pdf",
                uploader="zhangsan",
                uploader_id=11,
                department_name="某某科",
                clinic_space_id=20,
                clinic_space_name="某某科室库",
                target_folder_path="安全生产/消防安全",
                folder_action="create",
                status="ready",
                reason="ready",
            )
        ],
    )
    script_mod.print_text_report(report)
    output = capsys.readouterr().out
    assert "迁移文件=doc.pdf" in output
    assert "科室库名称=某某科室库" in output
    assert "上传人=zhangsan" in output
    assert "科室名称=某某科" in output
