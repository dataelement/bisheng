"""F078 isolated Elasticsearch 8.x maintenance acceptance.

Only runs against an explicitly supplied dedicated local cluster whose name starts
with codex-f078-. No application API/tenant/authentication contract is changed.
Every test document and pipeline has an e2e-f078- prefix; index cleanup additionally
requires this suite's ownership metadata. Never point this at a business cluster.
"""

import asyncio
import json
import os
import time
import uuid
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from elasticsearch import AsyncElasticsearch

from scripts.article_reshard_plan import MigrationError
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
@pytest.mark.parametrize("strategy,verification", [("split", "native"), ("split", "full"), ("reindex", "full")])
async def test_migration_freezes_all_acknowledged_operations_and_restores_live_access(
    isolated_es, alias, strategy, verification
):
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
        plan = await run_migration(es, 3, run_id=run_id, batch_size=100, strategy=strategy, verification=verification)
        assert plan["mode"] == "dry_run"
        result = await run_migration(
            es,
            3,
            apply=True,
            writers_paused=True,
            run_id=run_id,
            poll_seconds=0.05,
            batch_size=100,
            strategy=strategy,
            verification=verification,
        )
        assert result["mode"] == "complete" and result["documents"] == 2 and result["batch_size"] == 100
        assert result["verification"] == verification
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


@pytest.mark.parametrize("source_shards,target_shards,documents", [(1, 3, 0), (3, 6, 7)])
async def test_empty_and_multi_primary_split_with_default_routing_space(
    isolated_es, source_shards, target_shards, documents
):
    """AC-20, AC-22, AC-23: empty source and computed multi-primary routing space."""
    es = isolated_es
    await es.indices.create(
        index="channel_articles",
        settings={"number_of_shards": source_shards, "number_of_replicas": 0},
        mappings={"_meta": {"e2e_owner": OWNER}},
    )
    for n in range(documents):
        await es.index(index="channel_articles", id=PREFIX + str(n), routing="r" + str(n), document={"title": str(n)})
    result = await run_migration(
        es, target_shards, apply=True, writers_paused=True, run_id=PREFIX + uuid.uuid4().hex, poll_seconds=0.05
    )
    assert result["documents"] == documents
    for n in range(documents):
        assert (await es.get(index="channel_articles", id=PREFIX + str(n), routing="r" + str(n)))["_source"] == {
            "title": str(n)
        }


async def test_split_response_loss_keeps_original_and_verified_backup_without_replay(isolated_es, monkeypatch):
    """AC-24, AC-25: real split accepted before simulated response loss."""
    es = isolated_es
    await es.indices.create(
        index="channel_articles",
        settings={"number_of_shards": 1, "number_of_replicas": 0},
        mappings={"_meta": {"e2e_owner": OWNER}},
    )
    await es.index(index="channel_articles", id=PREFIX + "keep", document={"title": "keep"})
    original_split = es.indices.split

    async def lose_response(**kwargs):
        await original_split(**kwargs)
        raise TimeoutError("simulated response loss after split accepted")

    monkeypatch.setattr(es.indices, "split", lose_response)
    run_id = PREFIX + uuid.uuid4().hex
    with pytest.raises(TimeoutError):
        await run_migration(es, 3, apply=True, writers_paused=True, run_id=run_id, poll_seconds=0.05)
    status = await run_migration(es, 3, status=True, run_id=run_id)
    assert status["phase"] == "SPLITTING_PENDING" and status["write_block"]
    assert status["current_article_indices"] == ["channel_articles"]
    for name in ["channel_articles", status["backup"], status["target"]]:
        assert (await es.get(index=name, id=PREFIX + "keep"))["_source"] == {"title": "keep"}
    with pytest.raises(MigrationError, match="artifacts already exist"):
        await run_migration(es, 3, apply=True, writers_paused=True, run_id=run_id + "-retry")


async def test_large_ngram_articles_split_without_reindex(isolated_es, monkeypatch):
    """AC-22 through AC-26: 4.6 MiB article body, ngram 1..3, 1 GiB heap."""
    from bisheng.channel.domain.es.article_index import ARTICLE_MAPPINGS, ARTICLE_SETTINGS

    es = isolated_es
    settings = deepcopy(ARTICLE_SETTINGS)
    settings.update(number_of_shards=1, number_of_replicas=0, refresh_interval="-1")
    await es.indices.create(
        index="channel_articles",
        settings=settings,
        mappings={"_meta": {"e2e_owner": OWNER}, "properties": ARTICLE_MAPPINGS},
    )
    text = "中粮频道文章测试数据0123456789,价格与市场分析。\n"
    unit_bytes = len(text.encode())
    hits = []
    for n in range(25):
        size = int(4.6 * 1024**2) if n == 0 else 128 * 1024
        content = text * (size // unit_bytes)
        document = {
            "title": "测试文章" + str(n),
            "content": content,
            "content_html": "<p>" + content + "</p>",
            "source_type": 1,
            "source_id": str(n),
        }
        hit = {"_id": PREFIX + str(n), "_routing": "r" + str(n % 4), "_source": document}
        hits.append(hit)
        await es.index(index="channel_articles", id=hit["_id"], routing=hit["_routing"], document=document)
    monkeypatch.setattr(es, "reindex", AsyncMock(side_effect=AssertionError("split must not reindex")))
    monkeypatch.setattr(es, "search", AsyncMock(side_effect=AssertionError("native must not scan bodies")))
    heap_samples = []
    stop = asyncio.Event()

    async def monitor():
        while not stop.is_set():
            stats = await es.nodes.stats(metric="jvm")
            heap_samples.extend(n["jvm"]["mem"]["heap_used_in_bytes"] for n in stats["nodes"].values())
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.25)
            except TimeoutError:
                continue

    task = asyncio.create_task(monitor())
    started = time.monotonic()
    try:
        result = await run_migration(
            es, 3, apply=True, writers_paused=True, run_id=PREFIX + uuid.uuid4().hex, poll_seconds=0.05
        )
    finally:
        stop.set()
        await task
    migration_seconds = round(time.monotonic() - started, 2)
    assert result["basis"] == {"count": 25} and result["verification"] == "native"
    es.reindex.assert_not_awaited()
    es.search.assert_not_awaited()
    # Independent test assertions, outside the timed script run.
    for hit in hits:
        actual = await es.get(index="channel_articles", id=hit["_id"], routing=hit["_routing"])
        assert actual["_source"] == hit["_source"]
    await es.index(index="channel_articles", id=PREFIX + "live", document={"title": "live"}, refresh=True)
    assert (await es.get(index="channel_articles", id=PREFIX + "live"))["_source"]["title"] == "live"
    print(
        "F078_LARGE_ARTICLES "
        + json.dumps(
            {
                "documents": 25,
                "content_bytes": sum(len(h["_source"]["content"].encode()) for h in hits),
                "largest_document_bytes": max(len(json.dumps(h["_source"], ensure_ascii=False).encode()) for h in hits),
                "migration_seconds": migration_seconds,
                "sampled_max_heap_bytes": max(heap_samples),
                "strategy": result["strategy"],
                "verification": result["verification"],
            }
        )
    )
