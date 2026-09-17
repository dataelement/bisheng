"""部门: 编码 bind; 对不上改为 as_group, 不按名合并, 不改 A 组织树."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.propose_dept import propose


def test_bind_same_external_id_keeps_a_pk():
    result = propose(
        [{"id": "10", "name": "财务", "external_id": "D1"}],
        [{"id": "88", "name": "财务部", "external_id": "D1"}],
    )
    assert result["map"][0]["action"] == "bind"
    assert result["map"][0]["a_dept_pk"] == "10"
    assert result["map"][0]["b_dept_pk"] == "88"


def test_same_name_different_code_becomes_group():
    result = propose(
        [{"id": "10", "name": "财务", "external_id": "A1"}],
        [{"id": "88", "name": "财务", "external_id": "B9"}],
    )
    assert result["map"][0]["action"] == "as_group"
    assert result["map"][0]["a_dept_pk"] == ""


def test_missing_external_id_as_group():
    result = propose(
        [{"id": "10", "name": "财务", "external_id": "A1"}],
        [{"id": "88", "name": "本地组", "external_id": ""}],
    )
    assert result["map"][0]["action"] == "as_group"


def test_tsv_null_literal_as_group_not_conflict():
    result = propose(
        [
            {"id": "118", "name": "A根", "external_id": "NULL"},
            {"id": "119", "name": "A访客", "external_id": "NULL"},
        ],
        [
            {"id": "1", "name": "默认组织", "external_id": "NULL"},
            {"id": "2", "name": "临时访客", "external_id": "NULL"},
        ],
    )
    assert result["conflict"] == []
    assert all(row["action"] == "as_group" for row in result["map"])
