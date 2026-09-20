"""用户映射: 员工编码 bind, 禁止按名合并."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.propose_user import propose


def test_bind_same_employee_code_keeps_a_user_id():
    result = propose(
        [{"user_id": "100", "user_name": "张三", "external_id": "E1", "external_code": "E1", "source": "sg"}],
        [{"user_id": "7", "user_name": "zhang", "external_id": "E1", "external_code": "E1"}],
    )
    assert result["map"][0]["action"] == "bind"
    assert result["map"][0]["a_user_id"] == "100"
    assert result["map"][0]["b_user_id"] == "7"
    assert result["conflict"] == []


def test_same_name_different_code_does_not_merge():
    result = propose(
        [{"user_id": "100", "user_name": "张三", "external_code": "A1", "source": "sg"}],
        [{"user_id": "7", "user_name": "张三", "external_code": "B9"}],
    )
    assert result["map"][0]["action"] == "create"
    assert result["map"][0]["a_user_id"] == ""


def test_duplicate_b_code_conflicts():
    result = propose(
        [{"user_id": "100", "external_code": "E1", "source": "sg"}],
        [
            {"user_id": "7", "external_code": "E1"},
            {"user_id": "8", "external_code": "E1"},
        ],
    )
    assert result["conflict"]
    assert "多个 B" in result["conflict"][0]["reason"]


def test_tsv_null_literal_is_not_employee_code():
    result = propose(
        [{"user_id": "100", "external_code": "E1", "source": "sg"}],
        [
            {"user_id": "1", "user_name": "a", "external_id": "NULL", "external_code": "NULL"},
            {"user_id": "2", "user_name": "b", "external_id": "NULL", "external_code": "NULL"},
        ],
    )
    assert result["conflict"] == []
    assert result["manual"] == []
    assert {row["b_user_id"] for row in result["map"]} == {"1", "2"}
    assert all(row["action"] == "create" and row["employee_code"] == "" for row in result["map"])


def test_a_local_and_sg_same_code_prefers_sg():
    result = propose(
        [
            {"user_id": "1", "external_code": "E1", "source": "local"},
            {"user_id": "2", "external_code": "E1", "source": "sg"},
        ],
        [{"user_id": "9", "external_code": "E1"}],
    )
    assert result["map"][0]["a_user_id"] == "2"
    assert "sg 优先" in result["map"][0]["note"]
