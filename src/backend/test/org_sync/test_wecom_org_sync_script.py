"""Payload-shaping tests for ``scripts/wecom_org_sync.py`` (no-Gateway sync).

The script's I/O paths (WeCom API, HMAC push) are exercised by hand against a
real deployment; what is covered here is the mapping onto the backend's
``gateway-wecom-org-sync`` contract, where a silent shape mistake would show up
as "sync ran, nothing changed" in production.
"""

from bisheng.org_sync.domain.schemas.remote_dto import RemoteDepartmentDTO, RemoteMemberDTO
from bisheng.org_sync.domain.services.wecom_payload import build_request
from scripts.wecom_org_sync import (
    SOURCE,
    build_department_items,
    build_member_items,
    build_payload,
    chunked,
)

TS = 1_760_000_000


def test_department_mapping_uses_sort_not_sort_order() -> None:
    items = build_department_items(
        [
            RemoteDepartmentDTO(external_id=1, name="HQ", parent_external_id=None, sort_order=7),
            RemoteDepartmentDTO(external_id=2, name="R&D", parent_external_id=1, sort_order=0),
        ]
    )

    assert items == [
        {"external_id": "1", "name": "HQ", "parent_external_id": None, "sort": 7},
        {"external_id": "2", "name": "R&D", "parent_external_id": "1", "sort": 0},
    ]


def test_member_mapping_keeps_empty_secondary_list() -> None:
    # The key must be present (even as []) or the backend preserves stale
    # secondary-department memberships instead of reconciling them.
    items = build_member_items(
        [
            RemoteMemberDTO(
                external_id="zhangsan",
                name="张三",
                email="z@example.com",
                phone=None,
                primary_dept_external_id="2",
                secondary_dept_external_ids=[],
            )
        ],
        TS,
    )

    assert items[0]["secondary_dept_external_ids"] == []
    assert items[0]["department_admin_external_ids"] == []
    assert items[0]["source"] == SOURCE
    assert items[0]["external_user_id"] == "zhangsan"
    assert items[0]["primary_dept_external_id"] == "2"
    assert items[0]["ts"] == TS
    assert items[0]["user_attrs"] == {"name": "张三", "email": "z@example.com", "phone": None}
    assert items[0]["account_disabled"] is False


def test_department_leaders_are_sent_for_grant_reconcile() -> None:
    items = build_member_items(
        [
            RemoteMemberDTO(
                external_id="boss",
                name="负责人",
                primary_dept_external_id="2",
                admin_dept_external_ids=["2", "78"],
            )
        ],
        TS,
    )

    assert items[0]["department_admin_external_ids"] == ["2", "78"]


def test_member_without_department_falls_back_to_root() -> None:
    items = build_member_items([RemoteMemberDTO(external_id="lisi", name="李四")], TS)
    assert items[0]["primary_dept_external_id"] is None


def test_inactive_members_are_marked_disabled() -> None:
    members = [
        RemoteMemberDTO(external_id="a", name="A", status="active"),
        RemoteMemberDTO(external_id="b", name="B", status="disabled"),
        RemoteMemberDTO(external_id="c", name="C", status="resigned"),
    ]

    flags = [item["account_disabled"] for item in build_member_items(members, TS)]

    assert flags == [False, True, True]


def test_payload_marks_authoritative_snapshot() -> None:
    payload = build_payload(
        [{"external_id": "1", "name": "HQ", "parent_external_id": None, "sort": 0}],
        [{"external_user_id": "zhangsan"}],
        TS,
        full_snapshot=True,
    )

    assert payload["departments"]["source"] == SOURCE
    assert payload["departments"]["full_snapshot"] is True
    assert payload["departments"]["source_ts"] == TS
    assert payload["departments"]["remove"] == []
    assert len(payload["members"]) == 1
    # No label unless asked: Gateway-shaped callers keep the sso_realtime default.
    assert "trigger_type" not in payload


def test_payload_can_label_the_run_as_scheduled() -> None:
    payload = build_payload([], [], TS, full_snapshot=True, trigger_type="scheduled")
    assert payload["trigger_type"] == "scheduled"


def test_build_request_matches_the_http_payload() -> None:
    dept = {"external_id": "1", "name": "HQ", "parent_external_id": None, "sort": 3}
    member = build_member_items([RemoteMemberDTO(external_id="u1", name="U")], TS)[0]

    request = build_request([dept], [member], TS, full_snapshot=True)

    assert request.departments.full_snapshot is True
    assert request.departments.upsert[0].external_id == "1"
    assert request.departments.upsert[0].sort == 3
    assert request.members[0].external_user_id == "u1"
    assert request.members[0].source == SOURCE


def test_chunked_keeps_single_chunk_by_default() -> None:
    assert chunked([1, 2, 3], 0) == [[1, 2, 3]]


def test_chunked_splits_and_preserves_order() -> None:
    assert chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
