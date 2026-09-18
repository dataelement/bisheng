"""无冲突时安装 proposed 为正式对照表."""

from pathlib import Path

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.install_maps import conflict_stems, install_official_maps


def test_conflict_blocks_install(tmp_path: Path):
    log_p4 = tmp_path / "logs"
    log_p4.mkdir()
    (log_p4 / "user-map.conflicts.csv").write_text(
        "employee_code,reason\nE1,同一员工编码对应多个 B 用户\n",
        encoding="utf-8",
    )
    assert conflict_stems(log_p4) == ["user-map.conflicts.csv"]
    pack = tmp_path / "pack"
    (pack / "p4").mkdir(parents=True)
    try:
        install_official_maps(pack, log_p4)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "user-map.conflicts.csv" in str(exc)


def test_installs_proposed_and_tenant(tmp_path: Path):
    pack = tmp_path / "pack"
    p4 = pack / "p4"
    p4.mkdir(parents=True)
    (p4 / "tenant-map.csv.example").write_text(
        "b_tenant_id,a_tenant_id,action,note\n1,1,bind,example\n",
        encoding="utf-8",
    )
    log_p4 = tmp_path / "logs"
    log_p4.mkdir()
    (log_p4 / "user-map.proposed.csv").write_text(
        "b_user_id,a_user_id,action\n7,,create\n",
        encoding="utf-8",
    )
    (log_p4 / "user-map.conflicts.csv").write_text("reason\n", encoding="utf-8")
    (log_p4 / "b-tenants.tsv").write_text("id\ttenant_code\n1\tdefault\n", encoding="utf-8")
    (log_p4 / "a-tenants.tsv").write_text("id\ttenant_code\n1\tdefault\n", encoding="utf-8")
    written = install_official_maps(pack, log_p4)
    assert "user-map.csv" in written
    text = (p4 / "user-map.csv").read_text(encoding="utf-8")
    assert "7" in text
    tenant = (p4 / "tenant-map.csv").read_text(encoding="utf-8")
    assert "1,1,bind" in tenant
