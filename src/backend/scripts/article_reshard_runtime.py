"""Explicit, fail-closed maintenance orchestration; no automatic cleanup or replay."""

import asyncio
import re
import time
import uuid
from copy import deepcopy

from scripts.article_reshard_plan import (
    DEFAULT_BATCH_SIZE,
    LOGICAL_INDEX,
    RUN_META_KEY,
    MigrationError,
    business_mapping,
    check_capacity,
    check_shards,
    check_split_eligibility,
    check_templates,
    copy_settings,
    enabled,
    fingerprint_index,
    make_plan,
    normalized_policy,
    safe_index_name,
    source_state,
    validate_batch_size,
)


def require_ack(response, stage, code=3):
    if response.get("acknowledged") is not True or response.get("shards_acknowledged") is False:
        raise MigrationError(f"{stage} was not fully acknowledged; inspect before retrying", code)


async def mark(es, plan, index, phase, **values):
    current = (await es.indices.get(index=index))[index]
    meta = deepcopy(current.get("mappings", {}).get("_meta", {}))
    record = meta.get(RUN_META_KEY, plan.metadata(phase))
    if record.get("run_id") != plan.run_id:
        raise MigrationError("migration ownership changed", 6)
    meta[RUN_META_KEY] = record | values | {"phase": phase}
    require_ack(await es.indices.put_mapping(index=index, body={"_meta": meta}), "metadata update")


async def create_entity(es, plan, index, shards, phase):
    mapping = deepcopy(plan.mappings)
    mapping.setdefault("_meta", {})[RUN_META_KEY] = plan.metadata(phase)
    response = await es.indices.create(index=index, settings=copy_settings(plan.settings, shards), mappings=mapping)
    require_ack(response, "migration entity creation")
    current = (await es.indices.get(index=index))[index]
    if current.get("aliases"):
        raise MigrationError("new migration entity unexpectedly has aliases", 6)


async def reserve_split(es, plan):
    # Both resize destinations must be absent. Reserve a separate source-UUID
    # name atomically, and persist intent before issuing either resize request.
    meta = deepcopy(plan.mappings.get("_meta", {}))
    meta[RUN_META_KEY] = plan.metadata("RESERVED")
    require_ack(
        await es.indices.create(
            index=plan.lock,
            settings={"number_of_shards": 1, "number_of_replicas": 0, "blocks.write": True},
            mappings={"_meta": meta},
        ),
        "source reservation",
    )
    current = (await es.indices.get(index=plan.lock))[plan.lock]
    if current.get("aliases"):
        raise MigrationError("reservation unexpectedly has aliases", 6)


async def resize_entity(es, plan, destination, *, clone, report, poll_seconds, timeout_seconds):
    phase = "CLONING" if clone else "SPLITTING"
    await mark(es, plan, plan.lock, phase + "_PENDING", recovery_index=destination)
    settings = {
        "index.number_of_shards": plan.source_shards if clone else plan.target_shards,
        "index.number_of_replicas": plan.settings.get("number_of_replicas", 1),
        "index.auto_expand_replicas": plan.settings.get("auto_expand_replicas", "false"),
        "index.blocks.write": True,
    }
    operation = es.indices.clone if clone else es.indices.split
    # A timeout/negative acknowledgment is uncertain: retain the reservation and
    # never resubmit, delete the destination or release the source automatically.
    response = await operation(index=plan.source, target=destination, settings=settings)
    require_ack(response, phase.lower())
    if report:
        report({"phase": phase, "run_id": plan.run_id, "target": destination, "strategy": plan.strategy})
    await mark(es, plan, plan.lock, phase, recovery_index=destination)
    started = time.monotonic()
    while True:
        health = await es.cluster.health(
            index=destination,
            wait_for_status="green",
            wait_for_no_relocating_shards=True,
            wait_for_no_initializing_shards=True,
            timeout="1s",
        )
        if (
            not health.get("timed_out")
            and health.get("status") == "green"
            and not health.get("initializing_shards")
            and not health.get("relocating_shards")
        ):
            break
        if time.monotonic() - started >= timeout_seconds:
            raise MigrationError("resize recovery observation timed out; inspect retained indices and recovery", 3)
        await asyncio.sleep(poll_seconds)
    current = (await es.indices.get(index=destination))[destination]
    if current.get("aliases"):
        raise MigrationError("resize destination unexpectedly has aliases", 6)
    # Resize copies the source business mappings, which may include a COMPLETE
    # record from an earlier migration. Replace only our own namespace.
    meta = deepcopy(current.get("mappings", {}).get("_meta", {}))
    meta[RUN_META_KEY] = plan.metadata(phase + "_RECOVERED")
    require_ack(await es.indices.put_mapping(index=destination, body={"_meta": meta}), "resize metadata")


async def block_and_refresh(es, index, *, frozen_resize=False):
    if frozen_resize:
        # Resize destinations are created write-blocked and never accept writes.
        # ES 8.12 returns shards_acknowledged=false for a repeated add_block.
        current = (await es.indices.get(index=index))[index]
        if not enabled(current["settings"]["index"].get("blocks", {}).get("write", False)):
            raise MigrationError("resize destination lost its initial write barrier", 3)
    else:
        response = await es.indices.add_block(index=index, block="write")
        require_ack(response, "write barrier")
        if any(not entry.get("blocked", False) or entry.get("exception") for entry in response.get("indices", [])):
            raise MigrationError("write barrier did not cover every source shard", 3)
    check_shards(await es.indices.refresh(index=index))


async def assert_source_unchanged(es, plan):
    name, current = await source_state(es)
    settings = current["settings"]["index"]
    if name != plan.source or settings["uuid"] != plan.source_uuid or current.get("aliases", {}) != plan.aliases:
        raise MigrationError("source identity or alias relationships changed", 6)
    if business_mapping(current.get("mappings", {})) != plan.mappings:
        raise MigrationError("source business mappings changed", 6)
    if normalized_policy(copy_settings(settings, plan.source_shards, copying=False)) != normalized_policy(
        copy_settings(plan.settings, plan.source_shards, copying=False)
    ):
        raise MigrationError("source index policy changed", 6)
    if not enabled(settings.get("blocks", {}).get("write", False)):
        raise MigrationError("source write barrier is no longer active", 6)


async def copy_data(es, plan, destination, *, report, poll_seconds, timeout_seconds):
    await mark(es, plan, destination, "COPY_PENDING")
    response = await es.reindex(
        body={
            "source": {"index": plan.source, "size": plan.batch_size},
            "dest": {"index": destination, "op_type": "create", "routing": "keep", "pipeline": "_none"},
        },
        wait_for_completion=False,
    )
    task_id = response.get("task")
    if not task_id:
        raise MigrationError("reindex task identifier missing; inspect active tasks before retry", 3)
    if report:
        report(
            {
                "phase": "COPYING",
                "run_id": plan.run_id,
                "target": destination,
                "task_id": task_id,
                "batch_size": plan.batch_size,
            }
        )
    await mark(es, plan, destination, "COPYING", task_id=task_id)
    started = time.monotonic()
    while True:
        task = await es.tasks.get(task_id=task_id)
        if task.get("completed"):
            result = task.get("response", {})
            if (
                task.get("error")
                or result.get("timed_out")
                or result.get("failures")
                or result.get("version_conflicts", 0)
            ):
                raise MigrationError("reindex task failed; recovery artifacts retained", 3)
            if result.get("created") != result.get("total") or result.get("updated", 0) or result.get("noops", 0):
                raise MigrationError("reindex did not exclusively create every source document", 3)
            return task_id
        if time.monotonic() - started >= timeout_seconds:
            raise MigrationError("reindex observation timed out; task may still be running", 3)
        await asyncio.sleep(poll_seconds)


async def verification_basis(es, plan, index):
    if plan.verification == "full":
        return await fingerprint_index(es, index, batch_size=plan.batch_size)
    response = await es.count(index=index)
    check_shards(response)
    return {"count": int(response["count"])}


async def verify_entity(es, plan, name, shards, basis, *, restored=False, content=True):
    current = (await es.indices.get(index=name))[name]
    actual = current["settings"]["index"]
    if int(actual["number_of_shards"]) != shards:
        raise MigrationError("actual target primary-shard count differs from configuration", 4)
    expected = normalized_policy(
        copy_settings(plan.settings, shards, copying=plan.strategy == "reindex" and not restored)
    )
    if normalized_policy(copy_settings(actual, shards, copying=False)) != expected:
        raise MigrationError("copied index policy differs from source business policy", 4)
    if business_mapping(current.get("mappings", {})) != plan.mappings:
        raise MigrationError("copied mappings differ from source business mappings", 4)
    if content and await verification_basis(es, plan, name) != basis:
        raise MigrationError("document verification failed for selected verification mode", 4)


async def existing_status(es, run_id):
    current_name, source = await source_state(es)
    identity = source["settings"]["index"]["uuid"]
    target = safe_index_name("reshard", run_id)
    source_record = source.get("mappings", {}).get("_meta", {}).get(RUN_META_KEY, {})
    candidates = [safe_index_name("lock", identity)]
    if source_record.get("run_id") == run_id and source_record.get("lock"):
        candidates.append(source_record["lock"])
    candidates.extend([target, safe_index_name("backup", identity)])
    meta = None
    for name in candidates:
        if await es.indices.exists(index=name):
            data = (await es.indices.get(index=name))[name]
            record = data.get("mappings", {}).get("_meta", {}).get(RUN_META_KEY, {})
            if record.get("run_id") == run_id:
                meta = record
                break
    if meta is None:
        raise MigrationError("no matching migration artifacts exist", 6)
    result = {
        key: meta.get(key)
        for key in (
            "run_id",
            "phase",
            "source",
            "source_uuid",
            "target",
            "backup",
            "target_shards",
            "task_id",
            "basis",
            "batch_size",
            "strategy",
            "verification",
            "lock",
            "recovery_index",
        )
    }
    result["mode"] = "status"
    result["write_block"] = enabled(source["settings"]["index"].get("blocks", {}).get("write", False))
    result["current_article_indices"] = [current_name]
    return result


async def refuse_active_tasks(es, plan):
    tasks = await es.tasks.list(actions="indices:data/write/reindex", detailed=True)
    for node in tasks.get("nodes", {}).values():
        for task in node.get("tasks", {}).values():
            description = task.get("description", "")
            if plan.source in description or LOGICAL_INDEX in description:
                raise MigrationError("an article reindex task is already active", 6)


def alias_actions(plan):
    aliases = deepcopy(plan.aliases)
    aliases.setdefault(LOGICAL_INDEX, {})["is_write_index"] = True
    if plan.source == LOGICAL_INDEX:
        actions = [{"remove_index": {"index": plan.source}}]
    else:
        actions = [{"remove": {"index": plan.source, "alias": name, "must_exist": True}} for name in plan.aliases]
    actions.extend({"add": {"index": plan.target, "alias": name, **values}} for name, values in aliases.items())
    return actions, aliases


async def verify_aliases(es, plan, expected):
    if list(await es.indices.get(index=LOGICAL_INDEX)) != [plan.target]:
        raise MigrationError("business alias does not resolve uniquely to the verified target", 5)
    for alias, values in expected.items():
        entries = await es.indices.get(index=alias)
        if plan.source in entries or entries.get(plan.target, {}).get("aliases", {}).get(alias) != values:
            raise MigrationError("an alias relationship differs from the cutover plan", 5)


async def run_migration(
    es,
    shards,
    *,
    apply=False,
    writers_paused=False,
    run_id=None,
    status=False,
    report=None,
    poll_seconds=1,
    timeout_seconds=3600,
    batch_size=DEFAULT_BATCH_SIZE,
    strategy="split",
    verification=None,
):
    validate_batch_size(batch_size)
    if strategy not in {"split", "reindex"}:
        raise MigrationError("strategy must be split or reindex")
    verification = verification or ("native" if strategy == "split" else "full")
    if verification not in {"native", "full"}:
        raise MigrationError("verification must be native or full")
    if strategy == "reindex" and verification != "full":
        raise MigrationError("native verification requires split; reindex requires full verification")
    if run_id is not None and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", run_id):
        raise MigrationError("run-id must contain 1-64 lowercase letters, digits or hyphens")
    if apply and (not writers_paused or not run_id):
        raise MigrationError("apply requires --writers-paused and an explicit --run-id")
    if status:
        if not run_id:
            raise MigrationError("status requires --run-id")
        return await existing_status(es, run_id)
    run_id = run_id or uuid.uuid4().hex
    plan = await make_plan(es, shards, run_id, batch_size=batch_size, strategy=strategy, verification=verification)
    _, source = await source_state(es)
    prior = source.get("mappings", {}).get("_meta", {}).get(RUN_META_KEY, {})
    if prior and prior.get("phase") != "COMPLETE":
        raise MigrationError("source is an unfinished migration target; inspect status before recovery", 6)
    if plan.source_shards == shards:
        return plan.report() | {"mode": "noop"}
    if (
        await es.indices.exists(index=plan.backup)
        or await es.indices.exists(index=plan.target)
        or await es.indices.exists(index=plan.lock)
    ):
        raise MigrationError("migration artifacts already exist; inspect status, do not overwrite", 6)
    if any(enabled(value) for value in plan.settings.get("blocks", {}).values()):
        raise MigrationError("source already has an index block; inspect before maintenance", 6)
    if plan.aliases.get(LOGICAL_INDEX, {}).get("is_write_index") is False:
        raise MigrationError("business alias explicitly disables writes; reconcile its policy first")
    if strategy == "split":
        await check_split_eligibility(es, plan)
        copy_settings(plan.settings, shards, copying=False)
    await refuse_active_tasks(es, plan)
    await check_templates(es, plan.backup)
    await check_templates(es, plan.target)
    if strategy == "split":
        await check_templates(es, plan.lock)
    capacity = await check_capacity(es, plan)
    if not apply:
        return plan.report() | {"mode": "dry_run", "capacity": capacity}
    # Creating the fixed source-UUID recovery name reserves this source before any source mutation.
    if strategy == "split":
        await reserve_split(es, plan)
    else:
        await create_entity(es, plan, plan.backup, plan.source_shards, "RESERVED")
    await block_and_refresh(es, plan.source)
    await assert_source_unchanged(es, plan)
    basis = await verification_basis(es, plan, plan.source)
    await mark(es, plan, plan.lock if strategy == "split" else plan.backup, "BASELINED", basis=basis)
    if strategy == "split":
        await resize_entity(
            es, plan, plan.backup, clone=True, report=report, poll_seconds=poll_seconds, timeout_seconds=timeout_seconds
        )
    else:
        await copy_data(
            es, plan, plan.backup, report=report, poll_seconds=poll_seconds, timeout_seconds=timeout_seconds
        )
    await block_and_refresh(es, plan.backup, frozen_resize=strategy == "split")
    await verify_entity(es, plan, plan.backup, plan.source_shards, basis)
    await mark(es, plan, plan.backup, "BACKUP_VERIFIED", basis=basis)
    if strategy == "split":
        await mark(es, plan, plan.lock, "BACKUP_VERIFIED", basis=basis)
    if strategy == "split":
        await resize_entity(
            es,
            plan,
            plan.target,
            clone=False,
            report=report,
            poll_seconds=poll_seconds,
            timeout_seconds=timeout_seconds,
        )
    else:
        await create_entity(es, plan, plan.target, plan.target_shards, "RESERVED")
        await copy_data(
            es, plan, plan.target, report=report, poll_seconds=poll_seconds, timeout_seconds=timeout_seconds
        )
    await block_and_refresh(es, plan.target, frozen_resize=strategy == "split")
    await verify_entity(es, plan, plan.target, plan.target_shards, basis)
    pipelines = {key: plan.settings.get(key, "_none") for key in ("default_pipeline", "final_pipeline")}
    require_ack(await es.indices.put_settings(index=plan.target, body={"index": pipelines}), "pipeline restoration")
    await verify_entity(es, plan, plan.target, plan.target_shards, basis, restored=True, content=False)
    await assert_source_unchanged(es, plan)
    if await verification_basis(es, plan, plan.source) != basis:
        raise MigrationError("source verification basis changed after baseline", 4)
    await mark(es, plan, plan.target, "CUTOVER_PENDING", basis=basis)
    if strategy == "split":
        await mark(es, plan, plan.lock, "CUTOVER_PENDING", basis=basis)
    actions, expected = alias_actions(plan)
    try:
        response = await es.indices.update_aliases(actions=actions)
        require_ack(response, "alias cutover", 5)
        if response.get("errors") or any(
            item.get("status", 200) >= 300 or item.get("error") for item in response.get("action_results", [])
        ):
            raise MigrationError("alias cutover contains failed actions", 5)
        await verify_aliases(es, plan, expected)
        require_ack(
            await es.indices.put_settings(index=plan.target, body={"index": {"blocks": {"write": False}}}),
            "target write restoration",
            5,
        )
        target = (await es.indices.get(index=plan.target))[plan.target]
        if enabled(target["settings"]["index"].get("blocks", {}).get("write", False)):
            raise MigrationError("target remains write blocked", 5)
        await mark(es, plan, plan.target, "COMPLETE", basis=basis)
        if strategy == "split":
            await mark(es, plan, plan.lock, "COMPLETE", basis=basis)
    except MigrationError as exc:
        if exc.code == 5:
            raise
        raise MigrationError("cutover finalization is uncertain; keep writers stopped and inspect status", 5) from exc
    except Exception as exc:
        raise MigrationError("cutover outcome is uncertain; keep writers stopped and inspect status", 5) from exc
    return plan.report() | {"mode": "complete", "documents": basis["count"], "basis": basis, "capacity": capacity}
