"""空间导出 JSON 与 dry-run: 部门作用域未映射则阻断, 不降 personal。"""

from __future__ import annotations

from test.upgrade_ab_fusion._packutil import P5, load_module

export = load_module("fusion_export_json", P5 / "export_to_json.py")
dry = load_module("fusion_dry_run", P5 / "20-dry-run.py")
keys = load_module("fusion_minio_keys", P5 / "list_minio_keys.py")


def test_assemble_extra_columns():
    dump = "\n".join(
        [
            "===SPACE===",
            "1\t库\tdesc\t9\t3\t0\t0\tprivate\t\t1",
            "===SCOPE===",
            "1\tdepartment\tdepartment\t3",
            "===FILES===",
            "11\t9\tu\t1\tf.pdf\t1\tspace_upload\t0\t\t10\tabc\t2\tobj/a\t\t\t\t\t\t\t\tmanager\tactive\tpreview/a\tthumbnails/t.jpg",
            "===MEMBERS===",
            "9\tcreator\tACTIVE\tuser\t9\towner\t1",
            "===TAGS===",
            '4\t公共\t\t["a"]\t0\t\t9',
            "===TAG_LINKS===",
            "1\t4\t0",
        ]
    )
    data = export.assemble(dump)
    assert data["space"]["is_favorite"] is True
    assert data["space"]["auth_type"] == "private"
    assert data["files"][0]["preview_file_object_name"] == "preview/a"
    assert data["files"][0]["thumbnails"] == "thumbnails/t.jpg"
    assert data["members"][0]["is_pinned"] is True
    assert data["tag_libraries"][0]["id"] == 4
    jobs = keys.list_pull_jobs(data)
    names = {j[1] for j in jobs}
    assert "11" in names
    assert "11.preview" in names
    assert "11.thumb" in names


def test_department_scope_unmapped_blocks():
    data = {
        "space": {"id": 1, "name": "科室库", "user_id": 9, "is_favorite": False},
        "scope": {"level": "department", "owner_type": "department", "owner_id": 3},
        "members": [],
        "files": [],
    }
    report = dry.dry_run_space(
        data,
        {9: {"a_user_id": "9", "b_user_id": "100", "action": "takeover"}},
        {},
        set(),
        {},
    )
    assert report["blocked"] is True
    assert any("禁止降级 personal" in r for r in report["reasons"])


def test_department_create_pending_does_not_block():
    data = {
        "space": {"id": 1, "name": "科室库", "user_id": 9, "is_favorite": False},
        "scope": {"level": "department", "owner_type": "department", "owner_id": 3},
        "members": [],
        "files": [],
    }
    report = dry.dry_run_space(
        data,
        {9: {"a_user_id": "9", "b_user_id": "100", "action": "takeover"}},
        {3: {"a_dept_pk": "3", "b_dept_pk": "", "action": "create"}},
        set(),
        {},
    )
    assert report["ok"] is True
    assert any(e["kind"] == "dept_pending_create" for e in report["exceptions"])
