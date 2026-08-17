"""Contracts for the production F048 visible reconciliation command."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bisheng.permission.domain.schemas import VisibleSourceProjectionDTO
from scripts import reconcile_f048_visible_projection as cli


def _source(*, fingerprint: str, subject: str = "user:7") -> VisibleSourceProjectionDTO:
    return VisibleSourceProjectionDTO(
        tenant_id=1,
        resource_type="knowledge_space",
        resource_id="42",
        visibility_class="ordinary",
        projected_subject=subject,
        source_kind="GRANT_ASSIGNEE",
        source_owner_key=f"grant_assignee:{fingerprint[0]}",
        source_locator=f"direct:{subject}",
        source_fingerprint=fingerprint,
        contribution_fingerprint=fingerprint,
        model_key="viewer",
        source_version=1,
        tuple_fingerprint="f" * 64,
        state="ACTIVE",
    )


def test_parse_defaults_to_dry_run_and_apply_requires_store_confirmation() -> None:
    args = cli.parse_args([])
    assert args.apply is False
    assert args.batch_size == 80

    with pytest.raises(SystemExit) as exc_info:
        cli.parse_args(["--apply"])
    assert exc_info.value.code == 2

    args = cli.parse_args(
        [
            "--apply",
            "--confirm-store-id",
            "store-1",
            "--operator-id",
            "7",
            "--batch-size",
            "90",
        ]
    )
    assert args.apply is True
    assert args.confirm_store_id == "store-1"
    assert args.batch_size == 90


def test_report_deduplicates_only_the_same_projected_subject_tuple() -> None:
    first = _source(fingerprint="a" * 64)
    second = _source(fingerprint="b" * 64)
    department = _source(
        fingerprint="c" * 64,
        subject="department:7#member",
    )
    user_group = _source(
        fingerprint="d" * 64,
        subject="user_group:9#member",
    )
    current = cli.CurrentRelease(
        catalog_id=1,
        catalog_key="catalog-v1",
        store_id="store-1",
        model_id="model-old",
        model_release_id=2,
        model_checksum="c" * 64,
        write_fenced=False,
    )

    report, upserts, retires, expected = cli._build_report(
        mode="dry-run",
        current=current,
        target_model_id=None,
        target_checksum="d" * 64,
        grants=(SimpleNamespace(),),
        assignee_count=4,
        canonical_sources=(first, second, department, user_group),
        persisted=(),
    )

    assert report.canonical_source_count == 4
    assert report.expected_tuple_count == 3
    assert upserts == (first, second, department, user_group)
    assert retires == ()
    assert expected == {
        ("user:7", "visible", "knowledge_space:42"),
        ("department:7#member", "visible", "knowledge_space:42"),
        ("user_group:9#member", "visible", "knowledge_space:42"),
    }


class _FGAClient:
    def __init__(self) -> None:
        self.writes = []
        self.checks = []

    @staticmethod
    def validate_business_mutation_size(operation_count: int) -> None:
        assert operation_count <= 90

    async def write_tuples(self, *, writes, ignore_duplicate_writes=False):
        self.writes.append((writes, ignore_duplicate_writes))

    async def batch_check(self, checks, consistency=None):
        self.checks.append((checks, consistency))
        return [True] * len(checks)


@pytest.mark.asyncio
async def test_reconcile_ensures_without_live_scan_and_verifies_usersets() -> None:
    client = _FGAClient()
    expected = frozenset(
        {
            ("department:7#member", "visible", "knowledge_space:42"),
            ("user_group:9#member", "visible", "knowledge_space:42"),
        }
    )

    await cli._ensure_expected_tuples(client, expected, batch_size=80)
    await cli._verify_expected_tuples(client, expected)

    assert client.writes == [
        (
            [
                {
                    "user": "department:7#member",
                    "relation": "visible",
                    "object": "knowledge_space:42",
                },
                {
                    "user": "user_group:9#member",
                    "relation": "visible",
                    "object": "knowledge_space:42",
                },
            ],
            True,
        )
    ]
    assert client.checks[0][1] == cli.HIGHER_CONSISTENCY
