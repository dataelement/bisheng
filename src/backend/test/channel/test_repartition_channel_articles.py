"""AC-19 through AC-26: real migration orchestration against observable ES responses."""

import pytest

from scripts.article_reshard_plan import LOGICAL_INDEX, MigrationError
from scripts.article_reshard_runtime import run_migration
from test.channel.article_reshard_fake import FakeEs


async def test_dry_run_has_zero_mutations():
    es = FakeEs()
    result = await run_migration(es, 3, run_id="test")
    assert result["mode"] == "dry_run" and es.writes == []


@pytest.mark.parametrize("alias", [False, True])
async def test_success_includes_unsearchable_writes_and_preserves_recovery(alias):
    es = FakeEs(alias=alias)
    es.docs[es.source]["deleted"] = {"_id": "deleted", "_source": {"title": "remove"}}
    es.pending[es.source].append(("deleted", None))
    result = await run_migration(es, 3, apply=True, writers_paused=True, run_id="test")
    target = result["target"]
    assert list(await es.indices.get(index=LOGICAL_INDEX)) == [target]
    assert set(es.docs[target]) == {"old", "new"}
    assert es.docs[target]["old"]["_source"]["title"] == "after"
    assert es.docs[result["backup"]] == es.docs[target]
    assert es.writes.index(("block", es.source)) < es.writes.index(("refresh", es.source))
    assert not es.indexes[target]["settings"]["index"]["blocks"]["write"]
    assert int(es.indexes[target]["settings"]["index"]["number_of_shards"]) == 3
    before = list(es.writes)
    assert (await run_migration(es, 3, apply=True, writers_paused=True, run_id="next"))["mode"] == "noop"
    assert es.writes == before


@pytest.mark.parametrize("fault", ["task_failed", "corrupt", "template_alias"])
async def test_failed_precondition_or_copy_never_cuts_over(fault):
    es = FakeEs(fault=fault)
    with pytest.raises(MigrationError):
        await run_migration(
            es,
            3,
            apply=True,
            writers_paused=True,
            run_id="test",
            strategy="reindex" if fault == "task_failed" else "split",
            verification="full",
        )
    assert LOGICAL_INDEX in es.indexes and not any(w[0] == "cutover" for w in es.writes)
    if fault == "template_alias":
        assert es.writes == []


async def test_cutover_unknown_keeps_target_blocked_and_retry_does_not_repeat_delete():
    es = FakeEs(fault="cutover_unknown")
    with pytest.raises(MigrationError) as error:
        await run_migration(es, 3, apply=True, writers_paused=True, run_id="test")
    assert error.value.code == 5
    target = next(iter(await es.indices.get(index=LOGICAL_INDEX)))
    assert es.indexes[target]["settings"]["index"]["blocks"]["write"]
    count = len(es.writes)
    with pytest.raises(MigrationError):
        await run_migration(es, 3, apply=True, writers_paused=True, run_id="test")
    assert len(es.writes) == count


async def test_existing_run_and_missing_maintenance_flag_fail_without_source_mutation():
    es = FakeEs()
    with pytest.raises(MigrationError):
        await run_migration(es, 3, apply=True, run_id="test")
    assert es.writes == []


@pytest.mark.parametrize("fault", ["red", "disk", "shards", "active_task", "prior_backup", "source_block"])
async def test_unsafe_preflight_is_read_only(fault):
    from scripts.article_reshard_plan import safe_index_name

    es = FakeEs()
    if fault == "red":
        es.cluster.health.return_value = {"status": "red"}
    elif fault == "disk":
        es.nodes.stats.return_value["nodes"]["n"]["fs"]["total"]["available_in_bytes"] = 1
    elif fault == "shards":
        es.cluster.get_settings.return_value = {"persistent": {"cluster.max_shards_per_node": 2}}
    elif fault == "active_task":
        es.tasks.list.return_value = {
            "nodes": {"n": {"tasks": {"1": {"description": "reindex from channel_articles"}}}}
        }
    elif fault == "prior_backup":
        es.indexes[safe_index_name("backup", "sourceUUID")] = es.indexes[es.source]
    else:
        es.indexes[es.source]["settings"]["index"]["blocks"] = {"write": True}
    with pytest.raises(MigrationError):
        await run_migration(es, 3, apply=True, writers_paused=True, run_id="preflight")
    assert es.writes == []


async def test_related_filtered_alias_policy_is_retained():
    es = FakeEs(alias=True)
    policy = {"filter": {"term": {"title": "after"}}, "search_routing": "u", "is_hidden": True}
    es.indexes[es.source]["aliases"]["related"] = policy
    result = await run_migration(es, 3, apply=True, writers_paused=True, run_id="aliases")
    assert es.indexes[result["target"]]["aliases"]["related"] == policy


async def test_final_metadata_ack_failure_is_classified_as_cutover_uncertainty():
    from scripts.article_reshard_plan import RUN_META_KEY

    es = FakeEs()
    original = es.put_mapping

    async def unacknowledged_complete(**kwargs):
        response = await original(**kwargs)
        if kwargs["body"]["_meta"][RUN_META_KEY]["phase"] == "COMPLETE":
            return {"acknowledged": False}
        return response

    es.put_mapping = unacknowledged_complete
    with pytest.raises(MigrationError) as error:
        await run_migration(es, 3, apply=True, writers_paused=True, run_id="final-ack")
    assert error.value.code == 5
    assert next(iter(await es.indices.get(index=LOGICAL_INDEX))) != es.source


async def test_batch_size_reaches_every_fingerprint_and_both_reindex_tasks():
    from unittest.mock import AsyncMock

    from scripts.article_reshard_plan import RUN_META_KEY

    es = FakeEs()
    es.search = AsyncMock(wraps=es.search)
    es.scroll = AsyncMock(wraps=es.scroll)
    es.reindex = AsyncMock(wraps=es.reindex)
    result = await run_migration(
        es,
        3,
        apply=True,
        writers_paused=True,
        run_id="small-batch",
        batch_size=1,
        strategy="reindex",
    )
    assert result["mode"] == "complete" and result["documents"] == 2
    assert result["batch_size"] == 1
    assert es.search.await_count == 4
    assert all(call.kwargs["size"] == 1 for call in es.search.call_args_list)
    assert es.scroll.await_count == 8
    assert es.reindex.await_count == 2
    assert all(call.kwargs["body"]["source"]["size"] == 1 for call in es.reindex.call_args_list)
    for name in (result["backup"], result["target"]):
        assert es.indexes[name]["mappings"]["_meta"][RUN_META_KEY]["batch_size"] == 1
    before = list(es.writes)
    status = await run_migration(es, 3, run_id="small-batch", status=True)
    assert status["batch_size"] == 1 and es.writes == before


@pytest.mark.parametrize("value", [0, -1, True, False, 1.5, "5", None])
async def test_invalid_runtime_batch_size_fails_before_any_es_operation(value):
    from unittest.mock import Mock

    es = Mock()
    with pytest.raises(MigrationError) as error:
        await run_migration(es, 3, batch_size=value)
    assert error.value.code == 2
    assert es.mock_calls == []


async def test_split_uses_clone_and_split_without_reindex_or_precreating_destinations():
    """AC-21 through AC-24: no reanalysis, exact source/backup/target content."""
    from unittest.mock import AsyncMock

    es = FakeEs()
    es.reindex = AsyncMock(side_effect=AssertionError("split must never reindex"))
    es.search = AsyncMock(wraps=es.search)
    es.indexes[es.source]["settings"]["index"]["number_of_routing_shards"] = "1024"
    result = await run_migration(es, 3, apply=True, writers_paused=True, run_id="split")
    assert result["strategy"] == "split" and result["mode"] == "complete"
    assert ("clone", result["backup"]) in es.writes and ("split", result["target"]) in es.writes
    assert ("create", result["backup"]) not in es.writes and ("create", result["target"]) not in es.writes
    es.reindex.assert_not_awaited()
    assert es.search.await_count == 0  # Native mode never reads or hashes bodies.
    assert result["verification"] == "native" and result["basis"] == {"count": 2}
    assert es.docs[result["backup"]] == es.docs[result["target"]]
    assert (await run_migration(es, 3, status=True, run_id="split"))["phase"] == "COMPLETE"


@pytest.mark.parametrize("source,target,routing", [(3, 1, 1536), (2, 3, 1024), (2, 6, 1024)])
async def test_incompatible_split_is_rejected_without_any_mutation(source, target, routing):
    es = FakeEs()
    es.indexes[es.source]["settings"]["index"].update(
        number_of_shards=str(source), number_of_routing_shards=str(routing)
    )
    with pytest.raises(MigrationError, match="explicit --strategy reindex"):
        await run_migration(es, target, apply=True, writers_paused=True, run_id="invalid-split")
    assert es.writes == []


async def test_yellow_source_is_rejected_before_reserving_or_blocking():
    es = FakeEs()
    es.cluster.health.return_value = {"status": "yellow"}
    with pytest.raises(MigrationError, match="green source"):
        await run_migration(es, 3, apply=True, writers_paused=True, run_id="yellow")
    assert es.writes == []


async def test_split_checks_per_node_temporary_segment_headroom():
    es = FakeEs()
    # Enough aggregate space, but one data node cannot hold clone + split work.
    node = es.nodes.stats.return_value["nodes"]["n"]
    from copy import deepcopy

    es.nodes.stats.return_value["nodes"]["small"] = deepcopy(node)
    es.nodes.stats.return_value["nodes"]["small"]["fs"]["total"]["available_in_bytes"] = 100300
    with pytest.raises(MigrationError, match="temporary segment headroom"):
        await run_migration(es, 3, apply=True, writers_paused=True, run_id="disk")
    assert es.writes == []


async def test_resize_unknown_retains_reservation_and_reports_pending_without_replay():
    """AC-25: accepted clone with lost response stays inspectable and blocked."""
    es = FakeEs(fault="resize_unknown")
    with pytest.raises(TimeoutError):
        await run_migration(es, 3, apply=True, writers_paused=True, run_id="unknown")
    status = await run_migration(es, 3, status=True, run_id="unknown")
    assert status["phase"] == "CLONING_PENDING" and status["write_block"]
    assert status["recovery_index"] == status["backup"]
    assert es.docs[status["backup"]] == es.docs[es.source]
    before = list(es.writes)
    with pytest.raises(MigrationError, match="artifacts already exist"):
        await run_migration(es, 3, apply=True, writers_paused=True, run_id="retry")
    assert es.writes == before and not any(w[0] == "cutover" for w in es.writes)


async def test_target_recovery_timeout_is_inspectable_even_before_target_metadata_is_written():
    es = FakeEs()

    async def health(**kwargs):
        if "reshard" in kwargs.get("index", ""):
            return {"status": "yellow", "timed_out": True, "initializing_shards": 1}
        return {"status": "green"}

    es.cluster.health.side_effect = health
    with pytest.raises(MigrationError, match="recovery observation timed out"):
        await run_migration(es, 3, apply=True, writers_paused=True, run_id="timeout", timeout_seconds=0)
    status = await run_migration(es, 3, status=True, run_id="timeout")
    assert status["phase"] == "SPLITTING" and status["basis"]["count"] == 2
    assert es.docs[status["backup"]] == es.docs[es.source]
    assert not any(w[0] == "cutover" for w in es.writes)


async def test_split_never_cuts_over_when_backup_content_is_corrupted():
    es = FakeEs()
    original = es.clone

    async def corrupt_backup(**kwargs):
        response = await original(**kwargs)
        es.docs[kwargs["target"]]["old"]["_source"]["title"] = "corrupt"
        return response

    es.clone = corrupt_backup
    with pytest.raises(MigrationError, match="document verification"):
        await run_migration(es, 3, apply=True, writers_paused=True, run_id="bad-backup", verification="full")
    assert not any(w[0] in {"split", "cutover"} for w in es.writes)


async def test_existing_source_uuid_reservation_prevents_overlapping_runs():
    from scripts.article_reshard_plan import safe_index_name

    es = FakeEs()
    es.indexes[safe_index_name("lock", "sourceUUID")] = es.indexes[es.source]
    with pytest.raises(MigrationError, match="artifacts already exist"):
        await run_migration(es, 3, apply=True, writers_paused=True, run_id="second")
    assert es.writes == []


async def test_optional_full_split_verification_detects_body_changes():
    from unittest.mock import AsyncMock

    es = FakeEs(fault="corrupt")
    es.search = AsyncMock(wraps=es.search)
    with pytest.raises(MigrationError, match="document verification"):
        await run_migration(es, 3, apply=True, writers_paused=True, run_id="full", verification="full")
    assert es.search.await_count == 3
    assert not any(w[0] == "cutover" for w in es.writes)


async def test_native_count_mismatch_still_prevents_cutover():
    es = FakeEs()
    original = es.split

    async def lose_document(**kwargs):
        response = await original(**kwargs)
        es.docs[kwargs["target"]].pop("old")
        return response

    es.split = lose_document
    with pytest.raises(MigrationError, match="document verification"):
        await run_migration(es, 3, apply=True, writers_paused=True, run_id="count")
    assert not any(w[0] == "cutover" for w in es.writes)


async def test_reindex_cannot_use_native_verification():
    es = FakeEs()
    with pytest.raises(MigrationError, match="reindex requires full"):
        await run_migration(es, 3, strategy="reindex", verification="native")
    assert es.writes == []
