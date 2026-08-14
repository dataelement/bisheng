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


def test_report_deduplicates_aggregate_tuple_and_never_schedules_unowned_delete() -> None:
    first = _source(fingerprint="a" * 64)
    second = _source(fingerprint="b" * 64)
    orphan = ("user:99", "visible", "knowledge_space:99")
    current = cli.CurrentRelease(
        catalog_id=1,
        catalog_key="catalog-v1",
        store_id="store-1",
        model_id="model-old",
        model_release_id=2,
        model_checksum="c" * 64,
        write_fenced=False,
    )

    report, upserts, retires, missing = cli._build_report(
        mode="dry-run",
        current=current,
        target_model_id=None,
        target_checksum="d" * 64,
        grants=(SimpleNamespace(),),
        assignee_count=2,
        canonical_sources=(first, second),
        persisted=(),
        live=frozenset({orphan}),
    )

    assert report.canonical_source_count == 2
    assert report.expected_tuple_count == 1
    assert report.missing_tuple_count == 1
    assert report.unowned_tuple_count == 1
    assert upserts == (first, second)
    assert retires == ()
    assert missing == {("user:7", "visible", "knowledge_space:42")}
