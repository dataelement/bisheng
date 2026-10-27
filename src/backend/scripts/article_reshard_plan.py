"""Read-only planning and bounded full-content verification for article maintenance."""

import fnmatch
import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, dataclass

from elasticsearch import NotFoundError
from loguru import logger

LOGICAL_INDEX = "channel_articles"
RUN_META_KEY = "bisheng_article_reshard"


class MigrationError(RuntimeError):
    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


def safe_index_name(kind, identity):
    return f"{LOGICAL_INDEX}__{kind}_{hashlib.sha256(identity.encode()).hexdigest()[:32]}"


def enabled(value):
    return value is True or str(value).lower() == "true"


def copy_settings(source, shards, *, copying=True):
    settings = deepcopy(source)
    for key in (
        "uuid",
        "creation_date",
        "creation_date_string",
        "provided_name",
        "version",
        "history_uuid",
        "resize",
        "verified_before_close",
        "blocks",
        "number_of_routing_shards",
    ):
        settings.pop(key, None)
    routing = settings.get("routing", {})
    if isinstance(routing, dict):
        routing.get("allocation", {}).pop("initial_recovery", None)
    if int(settings.get("routing_partition_size", 1)) >= shards and int(settings.get("routing_partition_size", 1)) > 1:
        raise MigrationError("routing_partition_size is incompatible with requested shards")
    settings["number_of_shards"] = shards
    for key in ("default_pipeline", "final_pipeline"):
        settings[key] = "_none" if copying else source.get(key, "_none")
    return settings


def business_mapping(mapping):
    result = deepcopy(mapping)
    meta = result.get("_meta", {})
    previous = meta.pop(RUN_META_KEY, None)
    if previous and previous.get("schema_version") != 1:
        raise MigrationError("unrecognized migration metadata namespace")
    if not meta:
        result.pop("_meta", None)
    return result


def normalized_policy(value):
    if isinstance(value, dict):
        return {key: normalized_policy(val) for key, val in value.items() if val != {}}
    if isinstance(value, list):
        return [normalized_policy(val) for val in value]
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def document_fingerprint(hits):
    count, total, xor = 0, 0, 0
    for hit in hits:
        if "_source" not in hit:
            raise MigrationError("source content is unavailable for full verification", 4)
        routing = hit.get("_routing", hit.get("fields", {}).get("_routing", [None])[0])
        number = int(hashlib.sha256(canonical([hit["_id"], routing, hit["_source"]]).encode()).hexdigest(), 16)
        count += 1
        total = (total + number) % (1 << 256)
        xor ^= number
    return {"count": count, "sum": f"{total:064x}", "xor": f"{xor:064x}"}


def check_shards(response):
    if response.get("_shards", {}).get("failed", 0):
        raise MigrationError("a read or refresh returned failed shards", 4)


async def fingerprint_index(es, index):
    count, total, xor = 0, 0, 0
    scroll_id = None
    try:
        response = await es.search(
            index=index,
            query={"match_all": {}},
            sort=["_doc"],
            size=500,
            scroll="2m",
            stored_fields=["_routing"],
            source=True,
            allow_partial_search_results=False,
        )
        while True:
            scroll_id = response.get("_scroll_id", scroll_id)
            check_shards(response)
            hits = response["hits"]["hits"]
            if not hits:
                break
            part = document_fingerprint(hits)
            count += part["count"]
            total = (total + int(part["sum"], 16)) % (1 << 256)
            xor ^= int(part["xor"], 16)
            if not scroll_id:
                raise MigrationError("full verification requires a scroll cursor", 4)
            response = await es.scroll(scroll_id=scroll_id, scroll="2m")
        return {"count": count, "sum": f"{total:064x}", "xor": f"{xor:064x}"}
    finally:
        if scroll_id:
            try:
                await es.clear_scroll(scroll_id=scroll_id)
            except Exception as exc:
                # Scroll cleanup does not change verified document content.
                logger.warning("scroll cleanup failed error_type={}", type(exc).__name__)


@dataclass
class MigrationPlan:
    source: str
    source_uuid: str
    target: str
    backup: str
    target_shards: int
    source_shards: int
    settings: dict
    mappings: dict
    aliases: dict
    documents: int
    run_id: str

    def report(self):
        return {key: value for key, value in asdict(self).items() if key not in {"mappings", "settings"}}

    def metadata(self, phase):
        return asdict(self) | {"schema_version": 1, "logical_index": LOGICAL_INDEX, "phase": phase}


async def source_state(es):
    try:
        values = await es.indices.get(index=LOGICAL_INDEX)
    except NotFoundError as exc:
        raise MigrationError("channel article source does not exist") from exc
    if len(values) != 1:
        raise MigrationError("channel article name must resolve to exactly one concrete index")
    name, state = next(iter(values.items()))
    if state.get("data_stream"):
        raise MigrationError("data stream migration is not supported")
    return name, state


async def make_plan(es, shards, run_id):
    if type(shards) is not int or shards < 1:
        raise MigrationError("requested primary shards must be a positive integer")
    source, state = await source_state(es)
    settings = deepcopy(state["settings"]["index"])
    mappings = business_mapping(state.get("mappings", {}))
    if mappings.get("_source", {}).get("enabled") is False:
        raise MigrationError("source _source is disabled")
    response = await es.count(index=source)
    check_shards(response)
    return MigrationPlan(
        source,
        settings["uuid"],
        safe_index_name("reshard", run_id),
        safe_index_name("backup", settings["uuid"]),
        shards,
        int(settings["number_of_shards"]),
        settings,
        mappings,
        deepcopy(state.get("aliases", {})),
        int(response["count"]),
        run_id,
    )


async def check_templates(es, index):
    try:
        response = await es.indices.simulate_index_template(name=index)
    except NotFoundError:
        response = None
    if response is not None:
        if response.get("template", {}).get("aliases"):
            raise MigrationError("template would attach aliases before cutover")
        return
    templates = await es.indices.get_template()
    for template in templates.values():
        if any(fnmatch.fnmatchcase(index, pattern) for pattern in template.get("index_patterns", [])):
            if template.get("aliases"):
                raise MigrationError("legacy template would attach aliases before cutover")


def watermark_bytes(value, total):
    text = str(value).lower()
    if text.endswith("%"):
        return total * (1 - float(text[:-1]) / 100)
    if text.replace(".", "", 1).isdigit() and float(text) <= 1:
        return total * (1 - float(text))
    for unit, multiplier in (("tb", 1024**4), ("gb", 1024**3), ("mb", 1024**2), ("kb", 1024), ("b", 1)):
        if text.endswith(unit):
            return float(text[: -len(unit)]) * multiplier
    raise MigrationError("cannot interpret cluster disk watermark")


async def check_capacity(es, plan):
    health = await es.cluster.health()
    if health.get("status") == "red":
        raise MigrationError("cluster is red; maintenance refused")
    config = await es.cluster.get_settings(include_defaults=True, flat_settings=True)
    config = config.get("defaults", {}) | config.get("persistent", {}) | config.get("transient", {})
    stats = await es.nodes.stats(metric="fs")
    nodes = [node for node in stats["nodes"].values() if any(role.startswith("data") for role in node.get("roles", []))]
    if not nodes:
        raise MigrationError("cannot determine data-node disk capacity")
    free = 0
    for node in nodes:
        space = node["fs"]["total"]
        reserve = watermark_bytes(
            config.get("cluster.routing.allocation.disk.watermark.high", "90%"), space["total_in_bytes"]
        )
        if space["available_in_bytes"] <= reserve:
            raise MigrationError("a data node is at or above the high disk watermark")
        free += space["available_in_bytes"] - reserve
    storage = await es.indices.stats(index=plan.source, metric="store")
    check_shards(storage)
    size = storage["_all"]["total"]["store"]["size_in_bytes"]
    if free <= 2 * size:
        raise MigrationError("insufficient estimated disk headroom for recovery copy and target")
    added = (plan.source_shards + plan.target_shards) * (1 + int(plan.settings.get("number_of_replicas", 1)))
    current = sum(health.get(key, 0) for key in ("active_shards", "unassigned_shards", "initializing_shards"))
    if current + added > int(config.get("cluster.max_shards_per_node", 1000)) * len(nodes):
        raise MigrationError("requested migration would exceed cluster shard capacity")
    return {"source_store_bytes": size, "estimated_extra_store_bytes": 2 * size, "additional_shard_copies": added}
