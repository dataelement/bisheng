from datetime import datetime

import pytest

from bisheng.knowledge.domain.models.knowledge_migration import (
    KnowledgeMigrationAttempt,
    KnowledgeMigrationBatch,
    KnowledgeMigrationBatchStatus,
    KnowledgeMigrationCheckpoint,
    KnowledgeMigrationFile,
    KnowledgeMigrationUnit,
    KnowledgeMigrationUnitStatus,
)
from bisheng.knowledge.domain.services.file_migration.state import (
    aggregate_batch_status,
    assert_batch_transition,
    calculate_progress,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("preflight_queued", "preflighting"),
        ("preflighting", "awaiting_confirmation"),
        ("preflighting", "queued"),
        ("awaiting_confirmation", "queued"),
        ("awaiting_confirmation", "abandoned"),
        ("queued", "running"),
        ("running", "succeeded"),
        ("running", "partial_success"),
        ("running", "failed"),
        ("partial_success", "queued"),
        ("failed", "queued"),
    ],
)
def test_batch_state_machine_accepts_defined_transitions(current: str, target: str):
    assert_batch_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("preflight_queued", "running"),
        ("awaiting_confirmation", "running"),
        ("abandoned", "queued"),
        ("succeeded", "running"),
        ("running", "awaiting_confirmation"),
    ],
)
def test_batch_state_machine_rejects_undefined_transitions(current: str, target: str):
    with pytest.raises(ValueError, match="invalid batch status transition"):
        assert_batch_transition(current, target)


def test_batch_progress_and_terminal_status_are_recomputed_from_units():
    statuses = [
        KnowledgeMigrationUnitStatus.SUCCEEDED.value,
        KnowledgeMigrationUnitStatus.POLICY_SKIPPED.value,
        KnowledgeMigrationUnitStatus.FAILED.value,
        KnowledgeMigrationUnitStatus.UNPROCESSED.value,
    ]

    progress = calculate_progress(statuses)

    assert progress.total_count == 4
    assert progress.executable_count == 3
    assert progress.completed_count == 3
    assert progress.succeeded_count == 1
    assert progress.skipped_count == 1
    assert progress.failed_count == 1
    assert progress.unprocessed_count == 1
    assert aggregate_batch_status(progress) == KnowledgeMigrationBatchStatus.PARTIAL_SUCCESS.value


def test_batch_with_no_executable_units_is_failed():
    progress = calculate_progress(
        [
            KnowledgeMigrationUnitStatus.POLICY_SKIPPED.value,
            KnowledgeMigrationUnitStatus.POLICY_SKIPPED.value,
        ]
    )

    assert progress.executable_count == 0
    assert (
        aggregate_batch_status(progress)
        == KnowledgeMigrationBatchStatus.FAILED.value
    )


def test_four_migration_models_expose_recovery_and_audit_fields():
    batch = KnowledgeMigrationBatch(
        batch_no="2c56b254-79ac-4bb0-a7db-4a2393c2218c",
        request_id="request-1",
        operator_id=1,
        operator_name="admin",
        source_selection_snapshot=[],
        source_spaces_snapshot=[],
        target_space_id=20,
        target_space_name="目标库",
    )
    unit = KnowledgeMigrationUnit(
        batch_id=1,
        unit_key="file:10",
        source_space_id=10,
        source_space_name="来源库",
    )
    file_row = KnowledgeMigrationFile(
        batch_id=1,
        unit_id=2,
        source_file_id=10,
        source_space_id=10,
        source_space_name="来源库",
        source_file_name="a.pdf",
        target_space_id=20,
        target_space_name="目标库",
        target_file_name="a.pdf",
    )
    attempt = KnowledgeMigrationAttempt(
        batch_id=1,
        unit_id=2,
        round_no=1,
        attempt_no=1,
        execution_token="token-digest",
        started_at=datetime.now(),
    )

    assert batch.status == KnowledgeMigrationBatchStatus.PREFLIGHT_QUEUED.value
    assert unit.status == KnowledgeMigrationUnitStatus.PLANNED.value
    assert unit.checkpoint == KnowledgeMigrationCheckpoint.PLANNED.value
    assert file_row.checkpoint == KnowledgeMigrationCheckpoint.PLANNED.value
    assert attempt.result == "running"


def test_soft_delete_is_only_allowed_for_terminal_batches():
    running = KnowledgeMigrationBatch(
        batch_no="running",
        request_id="request-running",
        operator_id=1,
        operator_name="admin",
        source_selection_snapshot=[],
        source_spaces_snapshot=[],
        target_space_id=20,
        target_space_name="目标库",
        status=KnowledgeMigrationBatchStatus.RUNNING.value,
    )
    succeeded = running.model_copy(
        update={
            "batch_no": "succeeded",
            "request_id": "request-succeeded",
            "status": KnowledgeMigrationBatchStatus.SUCCEEDED.value,
        }
    )

    assert running.can_soft_delete is False
    assert succeeded.can_soft_delete is True
