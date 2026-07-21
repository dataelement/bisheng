from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from scripts import dedupe_department_space_documents as script_mod


def _space(space_id: int, level: str) -> script_mod.SpaceSnapshot:
    return script_mod.SpaceSnapshot(space_id=space_id, level=level)


def _file(
    file_id: int,
    space_id: int,
    md5: str | None,
    *,
    status: int = 2,
    file_type: int = 1,
) -> script_mod.FileSnapshot:
    return script_mod.FileSnapshot(
        file_id=file_id,
        space_id=space_id,
        file_type=file_type,
        status=status,
        md5=md5,
        storage_objects=(
            script_mod.StorageObjectSnapshot(kind="original", name=f"original/{file_id}"),
            script_mod.StorageObjectSnapshot(kind="converted", name=str(file_id)),
        ),
    )


def _version(
    version_id: int,
    document_id: int,
    file_id: int,
    version_no: int,
    *,
    is_primary: bool,
) -> script_mod.VersionSnapshot:
    return script_mod.VersionSnapshot(
        version_id=version_id,
        document_id=document_id,
        file_id=file_id,
        version_no=version_no,
        is_primary=is_primary,
    )


def _base_inventory() -> script_mod.Inventory:
    spaces = (
        _space(1, "public"),
        _space(2, "public"),
        _space(10, "department"),
        _space(11, "department"),
    )
    files = (
        _file(100, 1, "history-only"),
        _file(101, 1, "same-md5"),
        _file(102, 2, "same-md5"),
        _file(200, 10, "old-department-version"),
        _file(201, 10, "same-md5"),
        _file(202, 10, "same-md5"),
        _file(203, 10, "   "),
        _file(204, 10, "SAME-MD5"),
        _file(205, 10, "history-only"),
        _file(206, 11, "same-md5"),
    )
    documents = (
        script_mod.DocumentSnapshot(document_id=1000, space_id=1, primary_version_id=1001),
        script_mod.DocumentSnapshot(document_id=2000, space_id=10, primary_version_id=2001),
    )
    versions = (
        _version(1000, 1000, 100, 1, is_primary=False),
        _version(1001, 1000, 101, 2, is_primary=True),
        _version(2000, 2000, 200, 1, is_primary=False),
        _version(2001, 2000, 201, 2, is_primary=True),
    )
    return script_mod.Inventory(
        spaces=spaces,
        files=files,
        documents=documents,
        versions=versions,
    )


def _base_plan(**kwargs) -> script_mod.DeduplicationPlan:
    return script_mod.build_deduplication_plan(_base_inventory(), **kwargs)


def test_parse_args_defaults_to_dry_run_and_accepts_repeated_filters(tmp_path: Path):
    args = script_mod.parse_args(
        [
            "--department-space-id",
            "10",
            "--department-space-id",
            "11",
            "--file-id",
            "201",
            "--report-dir",
            str(tmp_path),
        ]
    )

    assert args.apply is False
    assert args.department_space_ids == [10, 11]
    assert args.file_ids == [201]
    assert args.limit is None
    assert args.report_dir == tmp_path


@pytest.mark.parametrize("option", ["--department-space-id", "--file-id", "--limit"])
@pytest.mark.parametrize("value", ["0", "-1", "not-a-number"])
def test_parse_args_rejects_non_positive_ids(option: str, value: str):
    with pytest.raises(SystemExit) as exc_info:
        script_mod.parse_args([option, value])

    assert exc_info.value.code == 2


def test_parse_args_requires_apply_for_resume_and_rejects_range_mix(tmp_path: Path):
    report = tmp_path / "apply.json"
    with pytest.raises(SystemExit):
        script_mod.parse_args(["--resume-report", str(report)])
    with pytest.raises(SystemExit):
        script_mod.parse_args(["--resume-report", str(report), "--department-space-id", "10", "--apply"])


def test_single_tenant_preflight_rejects_multi_tenant_before_reads():
    assert script_mod.ensure_single_tenant(False) == 1
    with pytest.raises(script_mod.PreflightError, match="multi-tenant"):
        script_mod.ensure_single_tenant(True)


def test_scope_enum_uses_persisted_value():
    assert script_mod._enum_value(script_mod.KnowledgeSpaceLevelEnum.PUBLIC) == "public"


def test_planner_uses_scope_and_current_success_file_with_exact_md5():
    plan = _base_plan()

    assert [unit.unit_key for unit in plan.units] == [
        "legacy-file:202",
        "document:2000",
        "legacy-file:206",
    ]
    document_unit = next(unit for unit in plan.units if unit.unit_key == "document:2000")
    assert [item.file_id for item in document_unit.physical_files] == [200, 201]
    assert [item.file_id for item in document_unit.public_witnesses] == [101, 102]
    assert all(item.space_id in {1, 2} for item in document_unit.public_witnesses)
    assert plan.blank_md5_count == 1
    assert 205 not in {unit.primary_file_id for unit in plan.units}
    assert 204 not in {unit.primary_file_id for unit in plan.units}


def test_public_release_state_is_not_part_of_the_inventory_contract():
    assert "is_released" not in script_mod.SpaceSnapshot.__dataclass_fields__
    assert "simhash" not in script_mod.FileSnapshot.__dataclass_fields__
    plan = _base_plan()
    assert {w.file_id for unit in plan.units for w in unit.public_witnesses} == {101, 102}


def test_planner_skips_ineligible_current_files_and_blank_md5():
    inventory = _base_inventory()
    inventory = replace(
        inventory,
        files=(
            *inventory.files,
            _file(300, 10, "same-md5", status=1),
            _file(301, 10, "same-md5", file_type=0),
            _file(302, 10, None),
        ),
    )

    plan = script_mod.build_deduplication_plan(inventory)

    selected = {unit.primary_file_id for unit in plan.units}
    assert selected.isdisjoint({300, 301, 302})
    assert plan.blank_md5_count == 2


@pytest.mark.parametrize(
    ("document", "versions", "reason_code"),
    [
        (
            script_mod.DocumentSnapshot(document_id=3000, space_id=10, primary_version_id=9999),
            (_version(3001, 3000, 303, 1, is_primary=True),),
            "primary_pointer_mismatch",
        ),
        (
            script_mod.DocumentSnapshot(document_id=3000, space_id=10, primary_version_id=3001),
            (
                _version(3001, 3000, 303, 1, is_primary=True),
                _version(3002, 3000, 304, 2, is_primary=True),
            ),
            "primary_version_count_invalid",
        ),
    ],
)
def test_planner_skips_corrupt_version_graphs(document, versions, reason_code):
    inventory = _base_inventory()
    inventory = replace(
        inventory,
        files=(*inventory.files, _file(303, 10, "same-md5"), _file(304, 10, "other")),
        documents=(*inventory.documents, document),
        versions=(*inventory.versions, *versions),
    )

    plan = script_mod.build_deduplication_plan(inventory)

    assert 303 not in {unit.primary_file_id for unit in plan.units}
    assert reason_code in {item.reason_code for item in plan.skipped}


def test_planner_skips_cross_space_version_chain():
    inventory = _base_inventory()
    inventory = replace(
        inventory,
        files=(*inventory.files, _file(303, 10, "same-md5"), _file(304, 11, "other")),
        documents=(
            *inventory.documents,
            script_mod.DocumentSnapshot(document_id=3000, space_id=10, primary_version_id=3001),
        ),
        versions=(
            *inventory.versions,
            _version(3001, 3000, 303, 1, is_primary=True),
            _version(3002, 3000, 304, 2, is_primary=False),
        ),
    )

    plan = script_mod.build_deduplication_plan(inventory)

    assert 303 not in {unit.primary_file_id for unit in plan.units}
    assert "cross_space_version_chain" in {item.reason_code for item in plan.skipped}


def test_planner_filters_department_targets_without_reducing_public_witnesses():
    plan = _base_plan(department_space_ids=[10], file_ids=[201], limit=1)

    assert [unit.unit_key for unit in plan.units] == ["document:2000"]
    assert [item.file_id for item in plan.units[0].public_witnesses] == [101, 102]
    assert plan.department_space_ids == (10,)
    assert plan.public_space_ids == (1, 2)


def test_planner_rejects_public_or_historical_file_filters():
    with pytest.raises(script_mod.PreflightError, match="department current file"):
        _base_plan(file_ids=[101])
    with pytest.raises(script_mod.PreflightError, match="department current file"):
        _base_plan(file_ids=[200])


def test_plan_fingerprint_changes_when_version_or_witness_changes():
    unit = _base_plan(file_ids=[201]).units[0]
    changed_version = replace(unit, primary_version_id=9999)
    changed_witnesses = replace(unit, public_witnesses=unit.public_witnesses[:1])

    assert script_mod.fingerprint_unit(unit) != script_mod.fingerprint_unit(changed_version)
    assert script_mod.fingerprint_unit(unit) != script_mod.fingerprint_unit(changed_witnesses)


class _FakeReader:
    def __init__(
        self,
        plan: script_mod.DeduplicationPlan,
        *,
        revalidation: script_mod.RevalidationResult | None = None,
    ) -> None:
        self.plan = plan
        self.revalidation = revalidation
        self.build_calls = 0
        self.revalidate_calls: list[str] = []

    async def build_plan(self, _args) -> script_mod.DeduplicationPlan:
        self.build_calls += 1
        return self.plan

    async def revalidate(self, unit: script_mod.DeletionUnit) -> script_mod.RevalidationResult:
        self.revalidate_calls.append(unit.unit_key)
        return self.revalidation or script_mod.RevalidationResult(valid=True, unit=unit)


class _FakeOperations:
    def __init__(self, *, fail_at: str | None = None, residual: bool = False) -> None:
        self.fail_at = fail_at
        self.residual = residual
        self.calls: list[str] = []
        self.db_deleted_units: set[str] = set()
        self.existing_target_units: set[str] = set()

    def _record(self, value: str) -> None:
        self.calls.append(value)
        if self.fail_at == value:
            raise RuntimeError("injected failure")

    async def delete_milvus(self, file: script_mod.FileSnapshot) -> None:
        self._record(f"milvus:{file.file_id}")

    async def delete_elasticsearch(self, file: script_mod.FileSnapshot) -> None:
        self._record(f"elasticsearch:{file.file_id}")

    async def delete_minio(self, file: script_mod.FileSnapshot) -> None:
        self._record(f"minio:{file.file_id}")

    async def clear_permissions(self, file_id: int) -> None:
        self._record(f"openfga:{file_id}")

    async def verify_external_absent(self, unit: script_mod.DeletionUnit) -> dict:
        self._record(f"external-verify:{unit.unit_key}")
        return {"external_absent": True}

    async def delete_database_records(self, unit: script_mod.DeletionUnit) -> None:
        self._record(f"database:{unit.unit_key}")
        self.db_deleted_units.add(unit.unit_key)

    async def invalidate_derived_state(self, unit: script_mod.DeletionUnit) -> None:
        self._record(f"invalidate:{unit.unit_key}")

    async def verify_deleted(self, unit: script_mod.DeletionUnit) -> dict:
        self._record(f"verify:{unit.unit_key}")
        if self.residual:
            raise script_mod.ResidualDataError("residual data")
        return {"database_absent": True, "public_witnesses_unchanged": True}

    async def target_records_exist(self, unit: script_mod.DeletionUnit) -> bool:
        self._record(f"exists:{unit.unit_key}")
        return unit.unit_key in self.existing_target_units


async def test_dry_run_writes_report_without_constructing_operations(tmp_path: Path):
    plan = _base_plan(department_space_ids=[10], file_ids=[201])
    reader = _FakeReader(plan)
    factory_calls = 0

    def operations_factory():
        nonlocal factory_calls
        factory_calls += 1
        return _FakeOperations()

    args = script_mod.parse_args(["--report-dir", str(tmp_path)])
    exit_code = await script_mod.run(
        args,
        reader=reader,
        operations_factory=operations_factory,
        manage_context=False,
    )

    assert exit_code == script_mod.EXIT_OK
    assert factory_calls == 0
    reports = list(tmp_path.glob("dedupe-*.json"))
    assert len(reports) == 1
    payload = json.loads(reports[0].read_text(encoding="utf-8"))
    assert payload["schema_version"] == script_mod.REPORT_SCHEMA_VERSION
    assert payload["mode"] == "dry-run"
    assert payload["summary"]["planned"] == 1
    assert payload["units"][0]["status"] == "planned"
    assert payload["units"][0]["unit"]["public_witnesses"][0]["file_id"] == 101
    assert "token" not in json.dumps(payload).lower()


async def test_apply_deletes_complete_chain_in_order_and_keeps_public_witnesses(tmp_path: Path):
    plan = _base_plan(department_space_ids=[10], file_ids=[201])
    reader = _FakeReader(plan)
    operations = _FakeOperations()
    args = script_mod.parse_args(["--report-dir", str(tmp_path), "--apply"])

    exit_code = await script_mod.run(
        args,
        reader=reader,
        operations_factory=lambda: operations,
        manage_context=False,
    )

    assert exit_code == script_mod.EXIT_OK
    assert operations.calls == [
        "milvus:200",
        "elasticsearch:200",
        "minio:200",
        "openfga:200",
        "milvus:201",
        "elasticsearch:201",
        "minio:201",
        "openfga:201",
        "external-verify:document:2000",
        "database:document:2000",
        "invalidate:document:2000",
        "verify:document:2000",
    ]
    assert all("101" not in call and "102" not in call for call in operations.calls)
    payload = json.loads(next(tmp_path.glob("dedupe-*.json")).read_text(encoding="utf-8"))
    assert payload["summary"]["completed"] == 1
    assert payload["units"][0]["status"] == "completed"


async def test_database_delete_locks_snapshot_and_deletes_only_target_relations(monkeypatch):
    unit = _base_plan(department_space_ids=[10], file_ids=[201]).units[0]
    scopes = [
        script_mod.KnowledgeSpaceScope(
            space_id=10,
            level=script_mod.KnowledgeSpaceLevelEnum.DEPARTMENT,
            owner_type="department",
            owner_id=10,
        ),
        script_mod.KnowledgeSpaceScope(
            space_id=1,
            level=script_mod.KnowledgeSpaceLevelEnum.PUBLIC,
            owner_type="tenant_root_department",
            owner_id=1,
        ),
        script_mod.KnowledgeSpaceScope(
            space_id=2,
            level=script_mod.KnowledgeSpaceLevelEnum.PUBLIC,
            owner_type="tenant_root_department",
            owner_id=1,
        ),
    ]
    witnesses = [
        script_mod.KnowledgeFile(
            id=101,
            knowledge_id=1,
            file_name="public-1",
            file_type=1,
            status=2,
            md5="same-md5",
        ),
        script_mod.KnowledgeFile(
            id=102,
            knowledge_id=2,
            file_name="public-2",
            file_type=1,
            status=2,
            md5="same-md5",
        ),
    ]
    targets = [
        script_mod.KnowledgeFile(
            id=200,
            knowledge_id=10,
            file_name="history",
            file_type=1,
            status=2,
            md5="old-department-version",
        ),
        script_mod.KnowledgeFile(
            id=201,
            knowledge_id=10,
            file_name="current",
            file_type=1,
            status=2,
            md5="same-md5",
        ),
    ]
    document = script_mod.KnowledgeDocument(
        id=2000,
        knowledge_id=10,
        primary_version_id=2001,
    )
    versions = [
        script_mod.KnowledgeDocumentVersion(
            id=2000,
            document_id=2000,
            knowledge_file_id=200,
            version_no=1,
            is_primary=False,
        ),
        script_mod.KnowledgeDocumentVersion(
            id=2001,
            document_id=2000,
            knowledge_file_id=201,
            version_no=2,
            is_primary=True,
        ),
    ]

    class FakeResult:
        def __init__(self, rows):
            self.rows = list(rows)

        def all(self):
            return self.rows

        def first(self):
            return self.rows[0] if self.rows else None

    class FakeSession:
        def __init__(self):
            self.select_results = iter([scopes, witnesses, targets, [document], versions])
            self.statements = []
            self.committed = False
            self.rolled_back = False

        async def exec(self, statement):
            self.statements.append(statement)
            if getattr(statement, "is_select", False):
                return FakeResult(next(self.select_results))
            return FakeResult([])

        async def commit(self):
            self.committed = True

        async def rollback(self):
            self.rolled_back = True

    session = FakeSession()

    @asynccontextmanager
    async def fake_session_factory():
        yield session

    monkeypatch.setattr(script_mod, "get_async_db_session", fake_session_factory)

    await script_mod.BishengDeleteOperations().delete_database_records(unit)

    deleted_tables = [
        statement.table.name for statement in session.statements if getattr(statement, "is_delete", False)
    ]
    assert deleted_tables == [
        script_mod.TagLink.__tablename__,
        script_mod.ReviewTagLink.__tablename__,
        script_mod.ShareLink.__tablename__,
        script_mod.KnowledgeFileSimilarityCandidate.__tablename__,
        script_mod.PortalRecommendationFileProjection.__tablename__,
        script_mod.KnowledgeDocumentVersion.__tablename__,
        script_mod.KnowledgeDocument.__tablename__,
        script_mod.KnowledgeFile.__tablename__,
    ]
    target_delete = next(
        statement
        for statement in session.statements
        if getattr(statement, "is_delete", False) and statement.table.name == script_mod.KnowledgeFile.__tablename__
    )
    assert sorted(next(iter(target_delete.compile().params.values()))) == [200, 201]
    assert session.committed is True
    assert session.rolled_back is False


async def test_apply_skips_when_revalidation_detects_drift(tmp_path: Path):
    plan = _base_plan(department_space_ids=[10], file_ids=[201])
    reader = _FakeReader(
        plan,
        revalidation=script_mod.RevalidationResult(valid=False, reason_code="plan_drift"),
    )
    operations = _FakeOperations()
    args = script_mod.parse_args(["--report-dir", str(tmp_path), "--apply"])

    exit_code = await script_mod.run(
        args,
        reader=reader,
        operations_factory=lambda: operations,
        manage_context=False,
    )

    assert exit_code == script_mod.EXIT_OK
    assert operations.calls == []
    payload = json.loads(next(tmp_path.glob("dedupe-*.json")).read_text(encoding="utf-8"))
    assert payload["units"][0]["status"] == "skipped"
    assert payload["units"][0]["reason_code"] == "plan_drift"


async def test_apply_fails_fast_and_marks_remaining_units_pending(tmp_path: Path):
    plan = _base_plan(department_space_ids=[10])
    reader = _FakeReader(plan)
    operations = _FakeOperations(fail_at="elasticsearch:202")
    args = script_mod.parse_args(["--report-dir", str(tmp_path), "--apply"])

    exit_code = await script_mod.run(
        args,
        reader=reader,
        operations_factory=lambda: operations,
        manage_context=False,
    )

    assert exit_code == script_mod.EXIT_APPLY_ERROR
    payload = json.loads(next(tmp_path.glob("dedupe-*.json")).read_text(encoding="utf-8"))
    assert [item["status"] for item in payload["units"]] == ["failed", "pending"]
    assert payload["summary"]["failed"] == 1
    assert payload["summary"]["pending"] == 1
    assert payload["units"][0]["error_type"] == "RuntimeError"


async def test_apply_treats_post_delete_residual_as_failure(tmp_path: Path):
    plan = _base_plan(department_space_ids=[10], file_ids=[201])
    operations = _FakeOperations(residual=True)
    args = script_mod.parse_args(["--report-dir", str(tmp_path), "--apply"])

    exit_code = await script_mod.run(
        args,
        reader=_FakeReader(plan),
        operations_factory=lambda: operations,
        manage_context=False,
    )

    assert exit_code == script_mod.EXIT_APPLY_ERROR
    payload = json.loads(next(tmp_path.glob("dedupe-*.json")).read_text(encoding="utf-8"))
    assert payload["units"][0]["status"] == "failed"
    assert payload["units"][0]["error_type"] == "ResidualDataError"


async def test_report_failure_prevents_operations_construction(monkeypatch, tmp_path: Path):
    plan = _base_plan(department_space_ids=[10], file_ids=[201])
    factory_calls = 0

    def fail_write(_self, _payload):
        raise script_mod.ReportWriteError("write failed")

    def operations_factory():
        nonlocal factory_calls
        factory_calls += 1
        return _FakeOperations()

    monkeypatch.setattr(script_mod.ReportStore, "write", fail_write)
    args = script_mod.parse_args(["--report-dir", str(tmp_path), "--apply"])

    exit_code = await script_mod.run(
        args,
        reader=_FakeReader(plan),
        operations_factory=operations_factory,
        manage_context=False,
    )

    assert exit_code == script_mod.EXIT_REPORT_ERROR
    assert factory_calls == 0


async def test_multi_tenant_run_exits_before_reader_or_operations(monkeypatch, tmp_path: Path):
    plan = _base_plan(department_space_ids=[10], file_ids=[201])
    reader = _FakeReader(plan)
    factory_calls = 0

    async def initialize_context(*, config):
        del config

    async def close_context():
        return None

    def operations_factory():
        nonlocal factory_calls
        factory_calls += 1
        return _FakeOperations()

    monkeypatch.setattr(script_mod, "initialize_app_context", initialize_context)
    monkeypatch.setattr(script_mod, "close_app_context", close_context)
    monkeypatch.setattr(script_mod.settings.multi_tenant, "enabled", True)
    args = script_mod.parse_args(["--report-dir", str(tmp_path), "--apply"])

    exit_code = await script_mod.run(
        args,
        reader=reader,
        operations_factory=operations_factory,
        manage_context=True,
    )

    assert exit_code == script_mod.EXIT_INPUT_ERROR
    assert reader.build_calls == 0
    assert factory_calls == 0


async def test_scan_failure_returns_exit_three_without_constructing_operations(tmp_path: Path):
    class FailingReader(_FakeReader):
        async def build_plan(self, args):
            del args
            raise RuntimeError("scan failed")

    factory_calls = 0

    def operations_factory():
        nonlocal factory_calls
        factory_calls += 1
        return _FakeOperations()

    args = script_mod.parse_args(["--report-dir", str(tmp_path), "--apply"])
    exit_code = await script_mod.run(
        args,
        reader=FailingReader(_base_plan()),
        operations_factory=operations_factory,
        manage_context=False,
    )

    assert exit_code == script_mod.EXIT_SCAN_ERROR
    assert factory_calls == 0
    payload = json.loads(next(tmp_path.glob("dedupe-*.json")).read_text(encoding="utf-8"))
    assert payload["errors"] == [{"error_type": "RuntimeError", "exit_code": script_mod.EXIT_SCAN_ERROR}]


async def test_resume_with_missing_target_only_retries_post_commit_steps(tmp_path: Path):
    plan = _base_plan(department_space_ids=[10], file_ids=[201])
    source = tmp_path / "source.json"
    payload = script_mod.make_run_report(
        plan,
        mode="apply",
        run_id="resume-source",
        arguments={"apply": True},
    )
    payload["units"][0]["status"] = "failed"
    payload["units"][0]["steps"] = [
        {"name": "database_delete", "status": "completed"},
        {"name": "derived_invalidation", "status": "failed"},
    ]
    source.write_text(json.dumps(payload), encoding="utf-8")
    operations = _FakeOperations()
    args = script_mod.parse_args(["--resume-report", str(source), "--report-dir", str(tmp_path / "resumed"), "--apply"])

    exit_code = await script_mod.run(
        args,
        reader=_FakeReader(plan),
        operations_factory=lambda: operations,
        manage_context=False,
    )

    assert exit_code == script_mod.EXIT_OK
    assert operations.calls == [
        "exists:document:2000",
        "invalidate:document:2000",
        "verify:document:2000",
    ]


async def test_resume_preserves_skipped_units_without_retrying_them(tmp_path: Path):
    plan = _base_plan(department_space_ids=[10], file_ids=[201])
    source = tmp_path / "source-skipped.json"
    payload = script_mod.make_run_report(
        plan,
        mode="apply",
        run_id="resume-skipped-source",
        arguments={"apply": True},
    )
    payload["units"][0]["status"] = "skipped"
    payload["units"][0]["reason_code"] = "plan_drift"
    source.write_text(json.dumps(payload), encoding="utf-8")
    operations = _FakeOperations()
    args = script_mod.parse_args(["--resume-report", str(source), "--report-dir", str(tmp_path / "resumed"), "--apply"])

    exit_code = await script_mod.run(
        args,
        reader=_FakeReader(plan),
        operations_factory=lambda: operations,
        manage_context=False,
    )

    assert exit_code == script_mod.EXIT_OK
    assert operations.calls == []
    resumed = json.loads(next((tmp_path / "resumed").glob("dedupe-*.json")).read_text(encoding="utf-8"))
    assert resumed["units"][0]["status"] == "skipped"
    assert resumed["units"][0]["reason_code"] == "plan_drift"


def test_resume_report_rejects_public_target_overlap(tmp_path: Path):
    plan = _base_plan(department_space_ids=[10], file_ids=[201])
    payload = script_mod.make_run_report(
        plan,
        mode="apply",
        run_id="tampered",
        arguments={"apply": True},
    )
    payload["units"][0]["unit"]["physical_files"][0]["file_id"] = 101
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(script_mod.PreflightError, match="public witness"):
        script_mod.load_resume_report(path)


def test_impact_counts_preserve_favorites_and_audit_history():
    plan = _base_plan(department_space_ids=[10], file_ids=[201])
    unit = replace(
        plan.units[0],
        impact_counts={
            "tag_links": 2,
            "review_tag_links": 1,
            "share_links": 1,
            "similarity_candidates": 3,
            "recommendation_projections": 2,
            "favorite_references_preserved": 4,
            "audit_records_preserved": 1,
        },
    )

    payload = script_mod.deletion_unit_to_dict(unit)

    assert payload["impact_counts"]["favorite_references_preserved"] == 4
    assert payload["impact_counts"]["audit_records_preserved"] == 1
