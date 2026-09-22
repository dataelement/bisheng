"""个人库迁入科室库的路由、只读和恢复契约。"""

import json
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from scripts import move_personal_files_to_clinic as m


def file(file_id=101, **changes):
    return NS(
        **(
            {
                "id": file_id,
                "tenant_id": 1,
                "knowledge_id": 10,
                "file_type": 1,
                "file_name": f"{file_id}.pdf",
                "file_level_path": "/1/2",
                "level": 2,
                "deleted_at": None,
                "status": 2,
                "entry_type": "manager",
                "entry_status": "active",
                "original_uploader_id": 7,
                "user_id": 8,
            }
            | changes
        )
    )


@pytest.fixture
def snapshot():
    return {
        "spaces": [NS(id=i, tenant_id=1, name=str(i)) for i in (10, 20, 21)],
        "scopes": [
            NS(space_id=10, level="personal", owner_type="user"),
            NS(space_id=20, level="team_ks", owner_type="user"),
            NS(space_id=21, level="team", owner_type="user"),
        ],
        "bindings": [NS(space_id=21, department_id=5), NS(space_id=20, department_id=5)],
        "departments": [
            NS(id=6, parent_id=5, status="active", org_level="squad"),
            NS(id=5, parent_id=None, status="active", org_level="office"),
        ],
        "memberships": [NS(user_id=7, department_id=6, is_primary=1), NS(user_id=8, department_id=5, is_primary=1)],
        "users": [NS(user_id=7, delete=0), NS(user_id=8, delete=0)],
        "files": [
            file(1, file_type=0, file_name="A", file_level_path="", level=0),
            file(2, file_type=0, file_name="B", file_level_path="/1", level=1),
            file(),
        ],
        "versions": [NS(document_id=100, knowledge_file_id=101)],
    }


def test_path_original_uploader_and_first_bound_clinic(snapshot):
    plan = m.build_plan(snapshot, 1, ("A", "B"))
    assert plan["candidate_files"] == 1
    group = plan["groups"][0]
    assert group["target_space_id"] == 20
    assert group["folder_parts"] == ["A", "B"]
    assert group["files"][0]["uploader_id"] == 7
    assert group["files"][0]["office_id"] == 5
    assert m.build_plan(snapshot, 1, ("B",))["candidate_files"] == 0


def test_missing_original_uploader_falls_back_to_current(snapshot):
    snapshot["files"][-1].original_uploader_id = None
    entry = m.build_plan(snapshot, 1, ())["groups"][0]["files"][0]
    assert entry["uploader_id"] == 8
    assert entry["uploader_source"] == "user_id"


@pytest.mark.parametrize(
    "case,code",
    [
        ("no_user", "unavailable_uploader"),
        ("no_primary", "missing_primary_department"),
        ("multiple_primary", "ambiguous_primary_department"),
        ("no_office", "missing_office"),
        ("cycle", "department_cycle"),
        ("missing_parent", "unavailable_department"),
        ("archived", "unavailable_department"),
        ("no_clinic", "missing_clinic"),
        ("ordinary_team", "missing_clinic"),
        ("not_parsed", "not_parsed"),
        ("share", "not_manager"),
        ("missing_version", "invalid_version_chain"),
    ],
)
def test_each_ineligible_file_has_reason(snapshot, case, code):
    if case == "no_user":
        snapshot["files"][-1].original_uploader_id = 999
    elif case == "no_primary":
        snapshot["memberships"][0].is_primary = 0
    elif case == "multiple_primary":
        snapshot["memberships"].append(NS(user_id=7, department_id=5, is_primary=1))
    elif case == "no_office":
        snapshot["departments"][1].org_level = "dept"
    elif case == "cycle":
        snapshot["departments"][0].parent_id = 6
    elif case == "missing_parent":
        snapshot["departments"][0].parent_id = 999
    elif case == "archived":
        snapshot["departments"][1].status = "archived"
    elif case == "no_clinic":
        snapshot["bindings"] = []
    elif case == "ordinary_team":
        for scope in snapshot["scopes"][1:]:
            scope.owner_type = "user_group"
    elif case == "not_parsed":
        snapshot["files"][-1].status = 1
    elif case == "share":
        snapshot["files"][-1].entry_type = "share"
    elif case == "missing_version":
        snapshot["versions"] = []
    plan = m.build_plan(snapshot, 1, ())
    assert plan["candidate_files"] == 0
    assert plan["skipped"][0]["reason_code"] == code


def test_nearest_office_without_binding_does_not_use_higher_office_or_secondary(snapshot):
    snapshot["departments"][0].org_level = "office"
    snapshot["memberships"].append(NS(user_id=7, department_id=5, is_primary=0))
    plan = m.build_plan(snapshot, 1, ())
    assert plan["skipped"][0]["reason_code"] == "missing_clinic"


def test_deep_path_root_files_and_excluded_deleted_files(snapshot):
    snapshot["files"] += [
        file(3, file_type=0, file_name="C", file_level_path="/1/2", level=2),
        file(102, file_level_path="/1/2/3", level=3),
        file(103, file_level_path="", level=0),
        file(104, deleted_at="deleted"),
    ]
    snapshot["versions"] += [NS(document_id=102, knowledge_file_id=102), NS(document_id=103, knowledge_file_id=103)]
    plan = m.build_plan(snapshot, 1, ("A", "B"))
    assert {tuple(g["folder_parts"]) for g in plan["groups"]} == {("A", "B"), ("A", "B", "C")}
    assert m.build_plan(snapshot, 1, ())["candidate_files"] == 3


@pytest.mark.parametrize("case", ["duplicate", "broken", "version_outside", "split_target"])
def test_ambiguous_paths_or_version_split_are_skipped(snapshot, case):
    if case == "duplicate":
        snapshot["files"].append(file(9, file_type=0, file_name="A", file_level_path="", level=0))
    elif case == "broken":
        snapshot["files"][1].file_level_path = "/999"
    elif case == "version_outside":
        snapshot["versions"].append(NS(document_id=100, knowledge_file_id=999))
    else:
        snapshot["files"].append(file(102, file_level_path="/1", level=1))
        snapshot["versions"].append(NS(document_id=100, knowledge_file_id=102))
    plan = m.build_plan(snapshot, 1, ())
    assert plan["candidate_files"] == 0
    assert plan["skipped"]


@pytest.mark.parametrize("path", ["", "A//B", "A/../B", "A\\B"])
def test_invalid_path_rejected_before_runtime(path):
    with pytest.raises(SystemExit):
        m.parse_args(["--folder-path", path])


class FakeBackend:
    def __init__(self, snapshot):
        self.load_snapshot = AsyncMock(side_effect=lambda _, **kwargs: deepcopy(snapshot))
        self.operator = AsyncMock(return_value=NS(user_id=1, tenant_id=1))
        self.ensure_folder = AsyncMock(return_value=200)
        self.move_unit = AsyncMock(side_effect=self.move)

    @asynccontextmanager
    async def shared_storage(self, tenant_id):
        yield

    async def move(self, unit, checkpoint, **kwargs):
        unit["status"] = "succeeded"
        checkpoint()


def arguments(apply=False):
    return m.parse_args(
        ["--tenant-id", "1", "--folder-path", "A/B"] + (["--apply", "--operator-id", "1"] if apply else [])
    )


async def test_owner_fallback_flag_is_applied_only_after_operator_validation(snapshot, tmp_path):
    args = arguments(True)
    assert args.use_operator_as_file_owner is False
    args = m.parse_args(["--apply", "--operator-id", "1", "--tenant-id", "1", "--use-operator-as-file-owner"])
    backend = FakeBackend(snapshot)
    backend.operator.side_effect = ValueError("不是全局超级管理员")
    with pytest.raises(ValueError, match="不是全局超级管理员"):
        await m.execute(args, backend, tmp_path / "rejected.json")
    assert not getattr(backend, "use_operator_as_file_owner", False)
    backend.move_unit.assert_not_awaited()
    backend.operator.side_effect = None
    assert await m.execute(args, backend, tmp_path / "accepted.json") == 0
    assert backend.operator_id == 1 and backend.use_operator_as_file_owner is True


async def test_dry_run_no_business_writes(snapshot, tmp_path):
    backend, path = FakeBackend(snapshot), tmp_path / "report.json"
    assert await m.execute(arguments(), backend, path) == 0
    backend.operator.assert_not_awaited()
    backend.ensure_folder.assert_not_awaited()
    backend.move_unit.assert_not_awaited()
    assert json.loads(path.read_text()) == []
    assert not (tmp_path / "recovery").exists()
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("failure", ["route_changed", "external", "skip"])
async def test_failed_file_does_not_block_other_file_in_same_folder(snapshot, tmp_path, failure):
    snapshot["files"].append(file(102))
    snapshot["versions"].append(NS(document_id=102, knowledge_file_id=102))
    backend, path = FakeBackend(snapshot), tmp_path / "report.json"
    if failure == "route_changed":
        changed = deepcopy(snapshot)
        changed["files"][2].original_uploader_id = 999
        backend.load_snapshot.side_effect = [snapshot, changed, snapshot]
    else:

        async def move(unit, checkpoint, **kwargs):
            if unit["document_id"] == 100:
                if failure == "skip":
                    raise m.SkipFile("projection_not_ready", "投影尚未就绪")
                unit.update(before={"backup": True}, status="syncing")
                checkpoint()
                raise RuntimeError("ES failed")
            unit["status"] = "succeeded"

        backend.move_unit.side_effect = move
    assert await m.execute(arguments(True), backend, path) == (2 if failure == "external" else 0)
    rows = json.loads(path.read_text())
    assert [r["file_id"] for r in rows] == [101]
    assert set(rows[0]) == {"file_id", "file_name", "source_space_id", "source_folder", "reason"}
    assert rows[0]["reason"]
    journal = json.loads((tmp_path / "recovery" / path.name).read_text())
    assert len(journal["units"]) == (1 if failure == "external" else 0)
    assert "plan" not in journal and "errors" not in journal


async def test_preview_only_lists_matched_ineligible_files(snapshot, tmp_path):
    snapshot["files"] += [file(102, original_uploader_id=999), file(103, file_level_path="", level=0)]
    path = tmp_path / "report.json"
    await m.execute(arguments(), FakeBackend(snapshot), path)
    assert json.loads(path.read_text()) == [
        {
            "file_id": 102,
            "file_name": "102.pdf",
            "source_space_id": 10,
            "source_folder": "A/B",
            "reason": "上传人不存在或已停用",
        }
    ]


async def test_global_failure_records_all_matched_unprocessed_files(snapshot, tmp_path):
    backend, path = FakeBackend(snapshot), tmp_path / "report.json"
    backend.operator.side_effect = RuntimeError("账号不可用")
    with pytest.raises(RuntimeError, match="账号不可用"):
        await m.execute(arguments(True), backend, path)
    rows = json.loads(path.read_text())
    assert [row["file_id"] for row in rows] == [101]
    assert "账号不可用" in rows[0]["reason"]


@pytest.mark.parametrize("outcome", ["succeeded", "restored"])
async def test_compact_recovery_retains_needed_snapshot_and_updates_main_report(snapshot, tmp_path, outcome):
    backend, path = FakeBackend(snapshot), tmp_path / "report.json"

    async def fail(unit, checkpoint, **kwargs):
        unit.update(before={"backup": True}, status="syncing")
        checkpoint()
        raise RuntimeError("写入失败")

    backend.move_unit.side_effect = fail
    assert await m.execute(arguments(True), backend, path) == 2
    recovery = tmp_path / "recovery" / path.name
    journal = json.loads(recovery.read_text())
    assert journal["units"][0]["before"] == {"backup": True}
    assert "plan" not in journal and "traceback" not in recovery.read_text()

    async def recover(unit, checkpoint, **kwargs):
        assert kwargs["recover"] is True
        unit["status"] = outcome
        checkpoint()

    backend.move_unit.side_effect = recover
    args = m.parse_args(["--tenant-id", "1", "--apply", "--operator-id", "1", "--recover-report", str(recovery)])
    assert await m.execute(args, backend, recovery) == 0
    rows = json.loads(path.read_text())
    if outcome == "succeeded":
        assert rows == []
    else:
        assert len(rows) == 1 and "恢复至原库" in rows[0]["reason"]
    assert json.loads(recovery.read_text())["units"] == []


def test_unconfirmed_broken_path_not_reported_for_specific_folder(snapshot):
    snapshot["files"].append(file(102, file_level_path="/999/2"))
    plan = m.build_plan(snapshot, 1, ("A", "B"))
    assert m.unmigrated_files({"plan": plan, "folder_parts": ["A", "B"], "units": []}) == []


async def test_report_write_failure_stops_before_next_document(snapshot, tmp_path, monkeypatch):
    snapshot["files"].append(file(102))
    snapshot["versions"].append(NS(document_id=102, knowledge_file_id=102))
    backend = FakeBackend(snapshot)

    async def move(unit, checkpoint):
        def unwritable(*args):
            raise OSError("disk full")

        monkeypatch.setattr(m, "save_report", unwritable)
        checkpoint()

    backend.move_unit.side_effect = move
    with pytest.raises(m.ReportWriteError):
        await m.execute(arguments(True), backend, tmp_path / "report.json")
    assert backend.move_unit.await_count == 1


async def test_recovery_rejects_report_from_other_script(snapshot, tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"execution_mode": "rehome_shared", "tenant_id": 1}))
    args = m.parse_args(["--tenant-id", "1", "--apply", "--operator-id", "1", "--recover-report", str(path)])
    backend = FakeBackend(snapshot)
    with pytest.raises(ValueError, match="恢复报告类型"):
        await m.execute(args, backend, path)
    backend.operator.assert_not_awaited()
