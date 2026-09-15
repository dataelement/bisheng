"""报表 version_key 冲突换新, 未映射 flow 跳过."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.report_sql import generate_report_sql


def test_new_version_key_on_conflict_and_minio_jobs():
    sql, maps = generate_report_sql(
        batch="b1",
        reports=[
            {
                "id": "1",
                "flow_id": "ffff",
                "file_name": "r.docx",
                "template_name": "tpl/1.docx",
                "version_key": "vk1",
                "object_name": "report/1.docx",
                "del_yn": "0",
                "tenant_id": "1",
            }
        ],
        maps={"flow": {"ffff": "aabb"}, "tenant": {"1": "1"}},
        a_existing_ids=set(),
        a_version_keys={"vk1"},
        next_id=9,
        a_tenant_default="1",
    )
    assert maps[0]["a_id"] == "9"
    assert maps[0]["version_key"] != "vk1"
    assert "INSERT INTO t_report" in sql
    assert "'aabb'" in sql
    jobs = maps[0]["extra_jobs"]
    assert any(j["dst"] == "report/9.docx" for j in jobs)
    assert any(j["dst"] == "tpl/9.docx" for j in jobs)


def test_skip_when_flow_unmapped():
    sql, maps = generate_report_sql(
        batch="b1",
        reports=[{"id": "1", "flow_id": "gone", "version_key": "x"}],
        maps={"flow": {}, "tenant": {"1": "1"}},
        a_existing_ids=set(),
        a_version_keys=set(),
        next_id=1,
        a_tenant_default="1",
    )
    assert maps == []
    assert "INSERT INTO t_report" not in sql
