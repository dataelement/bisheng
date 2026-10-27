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
        await run_migration(es, 3, apply=True, writers_paused=True, run_id="test")
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
