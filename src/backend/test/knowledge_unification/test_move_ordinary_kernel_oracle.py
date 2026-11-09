"""SQL and state oracle captured before the move execution hook was installed."""

import hashlib
import json
from datetime import datetime
from uuid import UUID

import pytest
import sqlalchemy as sa

from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem as Item
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.knowledge.domain.repositories.processing_job_repository import (
    ProcessingConfiguration,
    ProcessingJobRepository,
)
from bisheng.knowledge.domain.schemas.processing_job_acceptance import _digest
from test.knowledge_unification.test_job_repo import job_session as job_session
from test.knowledge_unification.test_job_repo import job_tenant as job_tenant

ORACLES = {
    "embedding_rebuild": (49, "8e9387191d310ef3ab1267560d4f9930c2107d795a2266f03b5abf8aee6db66c"),
    "file_reprocess": (49, "7fa859e050bd4fa41608219c67895b0993cbb0a570725ddf8978c9fd2bf86afc"),
    "file_resplit": (49, "8b7d29b1740e6de4ae88f25773c6e9c82d2852faa5f2c46e368a631a3024dbe6"),
    "metadata_schema_change": (38, "cce3afa94f87d53616c42c9beb35fa2d436903bf2dd0a7996712588ca77bee63"),
}


@pytest.mark.parametrize("kind", ["embedding_rebuild", "file_reprocess", "file_resplit", "metadata_schema_change"])
async def test_ordinary_sql_bindings_and_state_are_identical_to_pre_hook_kernel(job_session, kind):
    now = datetime(2026, 11, 5, 3)
    repo = ProcessingJobRepository(clock=lambda: now)
    parameters = {"metadata_schema_revision": 0, "metadata_schema_digest": _digest([])}
    config = ProcessingConfiguration(7, "index-7", metadata_schema_revision=0, metadata_schema_digest=_digest([]))
    job_id, item_id = str(UUID(int=1)), str(UUID(int=2))
    job_session.add(
        Job(
            id=job_id,
            tenant_id=101,
            space_id=1,
            kind=kind,
            idempotency_key="ordinary-oracle",
            request_hash="f" * 64,
            actor_user_id=11,
            actor_reference={"kind": "original"},
            parameters=parameters,
            scope_manifest=[{"file_id": 8}],
            expected_model_config_revision=7,
            expected_index_generation="index-7",
            total_count=1,
            pending_count=1,
            accepted_at=now,
            create_time=now,
            update_time=now,
        )
    )
    job_session.add(
        Item(
            id=item_id,
            tenant_id=101,
            job_id=job_id,
            file_id=8,
            document_id=108,
            version_id=208,
            expected_space_id=1,
            processing_snapshot={"original": "rule"},
            create_time=now,
            update_time=now,
        )
    )
    await job_session.commit()
    events, ids = [], {}

    def normalize(value):
        if type(value) is str:
            try:
                parsed = UUID(value)
            except ValueError:
                return value
            if str(parsed) == value:
                return ids.setdefault(value, f"uuid-{len(ids)}")
        if isinstance(value, (list, tuple)):
            return [normalize(v) for v in value]
        return value

    def capture(c, u, sql, params, context, many):
        events.append([sql, normalize(params)])

    sa.event.listen(job_session.bind.sync_engine, "before_cursor_execute", capture)
    lease = await repo.aclaim(job_session, job_id, configuration=config)
    lease = await repo.arenew(job_session, lease, configuration=config)
    first = await repo.aclaim_next_item(job_session, lease, configuration=config)
    assert await repo.asave_checkpoint(
        job_session, first.lease, configuration=config, step="native", checkpoint={"next": 1}
    )
    assert await repo.acomplete_item(job_session, first.lease, configuration=config, succeeded=False, error_code=10915)
    failed = await repo.afinalize(job_session, lease, configuration=config)
    result = await repo.aretry_failed(
        job_session,
        job_id,
        configuration=config,
        idempotency_key="retry",
        expected_job_revision=failed.revision,
        actor_user_id=11,
        actor_reference={"kind": "original"},
    )
    lease = await repo.aclaim(job_session, job_id, configuration=config)
    second = await repo.aclaim_next_item(job_session, lease, configuration=config)
    assert await repo.acomplete_item(
        job_session, second.lease, configuration=config, succeeded=True, result={"done": True}
    )
    final = await repo.afinalize(job_session, lease, configuration=config)
    state = [
        final.state,
        final.revision,
        final.claim_generation,
        final.succeeded_count,
        final.failed_count,
        final.pending_count,
        second.item.attempt,
        second.item.claim_generation,
        second.item.result,
        second.item.checkpoint,
        result.reused,
    ]
    digest = hashlib.sha256(
        json.dumps([events, state], ensure_ascii=False, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    print(kind, len(events), digest)
    assert (len(events), digest) == ORACLES[kind]
