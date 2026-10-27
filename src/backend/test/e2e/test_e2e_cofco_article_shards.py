"""F078 isolated Elasticsearch 8.x maintenance acceptance.

Only runs against an explicitly supplied dedicated local cluster whose name starts
with codex-f078-. No application API/tenant/authentication contract is changed.
Every test document and pipeline has an e2e-f078- prefix; index cleanup additionally
requires this suite's ownership metadata. Never point this at a business cluster.
"""

import os
import uuid

import pytest
import pytest_asyncio
from elasticsearch import AsyncElasticsearch

from scripts.article_reshard_runtime import run_migration

ES_URL = os.getenv("E2E_ARTICLE_SHARDS_ES_URL", "")
OWNER = "e2e-f078"
PREFIX = "e2e-f078-"
pytestmark = pytest.mark.skipif(not ES_URL, reason="dedicated E2E_ARTICLE_SHARDS_ES_URL is required")


async def cleanup(es):
    indexes = await es.indices.get(index="channel_articles*,e2e-f078-*", allow_no_indices=True)
    for name, body in indexes.items():
        if body.get("mappings", {}).get("_meta", {}).get("e2e_owner") == OWNER:
            await es.indices.delete(index=name)


@pytest_asyncio.fixture
async def isolated_es():
    es = AsyncElasticsearch(ES_URL, request_timeout=60)
    try:
        info = await es.info()
        assert info["cluster_name"].startswith("codex-f078-"), "refusing non-isolated ES cluster"
        await cleanup(es)
        assert not await es.indices.exists(index="channel_articles"), "foreign article index present"
        yield es
    finally:
        info = await es.info()
        if info["cluster_name"].startswith("codex-f078-"):
            await cleanup(es)
        await es.close()


@pytest.mark.parametrize("alias", [False, True])
async def test_migration_freezes_all_acknowledged_operations_and_restores_live_access(isolated_es, alias):
    """AC-14, AC-18, AC-19, AC-21, AC-22, AC-23, AC-24, AC-26: real ES full migration."""
    es = isolated_es
    run_id = PREFIX + uuid.uuid4().hex
    source = PREFIX + "source" if alias else "channel_articles"
    pipeline = PREFIX + "pipeline"
    await es.ingest.put_pipeline(
        id=pipeline,
        processors=[{"script": {"source": "ctx.ingest_count = (ctx.ingest_count == null ? 0 : ctx.ingest_count) + 1"}}],
    )
    try:
        await es.indices.create(
            index=source,
            settings={
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "refresh_interval": "-1",
                "default_pipeline": pipeline,
                "final_pipeline": pipeline,
                "analysis": {"analyzer": {"fold": {"type": "custom", "tokenizer": "keyword", "filter": ["lowercase"]}}},
            },
            mappings={"_meta": {"e2e_owner": OWNER}, "properties": {"title": {"type": "text", "analyzer": "fold"}}},
            aliases={"channel_articles": {}} if alias else {},
        )
        related = PREFIX + "filtered"
        policy = {"filter": {"term": {"title": "after"}}, "search_routing": "r", "is_hidden": True}
        await es.indices.update_aliases(actions=[{"add": {"index": source, "alias": related, **policy}}])
        await es.index(index=source, id=PREFIX + "updated", routing="r", document={"title": "before"}, refresh=True)
        await es.index(index=source, id=PREFIX + "deleted", document={"title": "delete"}, refresh=True)
        await es.index(index=source, id=PREFIX + "updated", routing="r", document={"title": "after"})
        await es.index(index=source, id=PREFIX + "new", document={"title": "new"})
        await es.delete(index=source, id=PREFIX + "deleted")
        # Default inspection must not refresh the unsearchable operations.
        plan = await run_migration(es, 3, run_id=run_id)
        assert plan["mode"] == "dry_run"
        result = await run_migration(es, 3, apply=True, writers_paused=True, run_id=run_id, poll_seconds=0.05)
        assert result["mode"] == "complete" and result["documents"] == 2
        data = await es.get(index="channel_articles", id=PREFIX + "updated", routing="r")
        assert data["_source"] == {"title": "after", "ingest_count": 2}
        assert not await es.exists(index="channel_articles", id=PREFIX + "deleted")
        actual = await es.indices.get(index="channel_articles")
        assert list(actual) == [result["target"]]
        assert actual[result["target"]]["settings"]["index"]["number_of_shards"] == "3"
        assert actual[result["target"]]["aliases"][related] == policy
        assert (await es.search(index=related, query={"match_all": {}}))["hits"]["total"]["value"] == 1
        await es.index(index="channel_articles", id=PREFIX + "live", document={"title": "live"}, refresh=True)
        assert (await es.get(index="channel_articles", id=PREFIX + "live"))["_source"]["ingest_count"] == 2
        await es.update(index="channel_articles", id=PREFIX + "live", doc={"title": "changed"}, refresh=True)
        assert (await es.get(index="channel_articles", id=PREFIX + "live"))["_source"]["title"] == "changed"
        await es.delete(index="channel_articles", id=PREFIX + "live", refresh=True)
        assert not await es.exists(index="channel_articles", id=PREFIX + "live")
        assert (await run_migration(es, 3, run_id=run_id))["mode"] == "noop"
    finally:
        await cleanup(es)
        await es.ingest.delete_pipeline(id=pipeline)


async def test_verified_backup_restores_removed_concrete_source(isolated_es):
    """AC-24, AC-25: exact alias recovery from a verified independent backup."""
    es = isolated_es
    await es.indices.create(
        index="channel_articles",
        settings={"number_of_shards": 1, "number_of_replicas": 0},
        mappings={"_meta": {"e2e_owner": OWNER}},
    )
    await es.index(index="channel_articles", id=PREFIX + "recover", document={"title": "keep"})
    result = await run_migration(
        es,
        3,
        apply=True,
        writers_paused=True,
        run_id=PREFIX + uuid.uuid4().hex,
        poll_seconds=0.05,
    )
    assert list(await es.indices.get(index="channel_articles")) == [result["target"]]
    # All application writers are still paused; inspect and restore the saved
    # original pipeline policy before making the verified recovery copy writable.
    await es.indices.put_settings(
        index=result["backup"], settings={"index": {"default_pipeline": "_none", "final_pipeline": "_none"}}
    )
    await es.indices.update_aliases(
        actions=[
            {"remove": {"index": result["target"], "alias": "channel_articles", "must_exist": True}},
            {"add": {"index": result["backup"], "alias": "channel_articles", "is_write_index": True}},
        ]
    )
    await es.indices.put_settings(index=result["backup"], settings={"index": {"blocks.write": False}})
    assert list(await es.indices.get(index="channel_articles")) == [result["backup"]]
    assert (await es.get(index="channel_articles", id=PREFIX + "recover"))["_source"] == {"title": "keep"}
    await es.index(index="channel_articles", id=PREFIX + "recovered-live", document={"title": "live"}, refresh=True)
    assert await es.exists(index="channel_articles", id=PREFIX + "recovered-live")
