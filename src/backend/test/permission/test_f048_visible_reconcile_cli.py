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

    with pytest.raises(SystemExit) as exc_info:
        cli.parse_args(
            [
                "--apply",
                "--confirm-store-id",
                "store-1",
                "--operator-id",
                "7",
                "--cleanup-orphan-tuples",
            ]
        )
    assert exc_info.value.code == 2

    args = cli.parse_args(
        [
            "--apply",
            "--confirm-store-id",
            "store-1",
            "--operator-id",
            "7",
            "--audit-orphan-tuples",
            "--orphan-object",
            "folder:97394",
            "--cleanup-orphan-tuples",
            "--confirm-orphan-checksum",
            "a" * 64,
        ]
    )
    assert args.cleanup_orphan_tuples is True
    assert args.confirm_orphan_checksum == "a" * 64
    assert args.orphan_object == ["folder:97394"]


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
        self.tuples = []

    @staticmethod
    def validate_business_mutation_size(operation_count: int) -> None:
        assert operation_count <= 90

    async def write_tuples(self, *, writes, ignore_duplicate_writes=False):
        self.writes.append((writes, ignore_duplicate_writes))

    async def batch_check(self, checks, consistency=None):
        self.checks.append((checks, consistency))
        return [True] * len(checks)

    async def read_tuples(self, consistency=None):
        assert consistency == cli.HIGHER_CONSISTENCY
        return self.tuples


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


@pytest.mark.asyncio
async def test_orphan_audit_uses_canonical_and_all_active_persisted_sources() -> None:
    client = _FGAClient()
    canonical = _source(fingerprint="a" * 64, subject="user:7")
    non_grant = _source(fingerprint="b" * 64, subject="user:8").model_copy(update={"source_kind": "RESOURCE"})
    retired = _source(fingerprint="c" * 64, subject="user:9").model_copy(update={"state": "RETIRED"})
    client.tuples = [
        {"user": "user:7", "relation": "visible", "object": "knowledge_space:42"},
        {"user": "user:8", "relation": "visible", "object": "knowledge_space:42"},
        {"user": "user:9", "relation": "visible", "object": "knowledge_space:42"},
        {"user": "user:10", "relation": "viewer", "object": "knowledge_space:42"},
    ]

    audit = await cli._audit_orphan_tuples(
        client,
        canonical_sources=(canonical,),
        persisted=(non_grant, retired),
    )

    assert audit.live_direct_visible_count == 3
    assert audit.supported_tuple_count == 2
    assert audit.missing_tuple_count == 0
    assert audit.orphan_tuples == (("user:9", "visible", "knowledge_space:42"),)


def test_orphan_cleanup_selection_can_limit_one_reviewed_resource() -> None:
    tuples = (
        ("user:7", "visible", "folder:97394"),
        ("user:8", "visible", "knowledge_space:4166"),
    )
    audit = cli.OrphanTupleAudit(
        live_direct_visible_count=2,
        supported_tuple_count=0,
        missing_tuple_count=0,
        orphan_tuple_count=2,
        missing_tuple_checksum=cli._checksum(()),
        orphan_tuple_checksum=cli._checksum(tuples),
        missing_tuples=(),
        orphan_tuples=tuples,
    )

    selection = cli._select_orphan_tuples(
        audit,
        object_filters=("folder:97394",),
    )

    assert selection.object_filters == ("folder:97394",)
    assert selection.tuple_count == 1
    assert selection.tuples == (("user:7", "visible", "folder:97394"),)
    assert selection.tuple_checksum == cli._checksum(selection.tuples)


def test_build_orphan_cleanup_plan_is_exact_and_resource_fenced() -> None:
    current = cli.CurrentRelease(
        catalog_id=1,
        catalog_key="catalog-v1",
        store_id="store-1",
        model_id="model-1",
        model_release_id=2,
        model_checksum="c" * 64,
        write_fenced=False,
    )
    scope = SimpleNamespace(
        tenant_id=7,
        resource_type="folder",
        resource_id="97394",
        version=11,
    )
    tuples = (
        ("department:310#member", "visible", "folder:97394"),
        ("user:839", "visible", "folder:97394"),
    )

    plan = cli._build_orphan_cleanup_plan(
        current=current,
        scope=scope,
        tuples=tuples,
        operator_id=191,
    )

    assert plan.operation_type == "VISIBLE_ORPHAN_CLEANUP"
    assert plan.scope_key == "folder:97394"
    assert (plan.expected_version, plan.target_version) == (11, 12)
    assert [(row.action, row.user, row.object) for row in plan.deltas] == [
        ("DELETE", "department:310#member", "folder:97394"),
        ("DELETE", "user:839", "folder:97394"),
    ]
