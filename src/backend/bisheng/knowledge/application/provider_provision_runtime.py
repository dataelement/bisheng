"""F026 provisioning composition. No instance, preset or model is implicit.

New spaces go to the tenant's single ready knowledge_provider_instance row. Models, chunking and
entity extraction are picked by the creator per space: either copy extract_config from a WeKnora
knowledge base that already has extraction enabled, or supply extract_config directly. Everything
WeKnora owns is probed live: model identity and output, the graph engine, the chosen extract_config.
Each space freezes what it was created with, so later edits in WeKnora neither require editing
BiSheng configuration nor invalidate existing spaces.
A declared graph engine or a model directory status alone is not a proof.
"""

import asyncio
import base64
import math
import re
import time
from contextlib import asynccontextmanager
from dataclasses import replace

import httpx
from loguru import logger
from sqlalchemy import select

from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.provider_provisioning import (
    ModelProof,
    Preset,
    PresetProof,
    ProviderProvisioning,
    ProviderTargetAbsent,
    digest,
    preflight,
)
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderInstance as Instance
from bisheng.knowledge.domain.repositories.provider_provision_repository import ProvisionRepository

# WeKnora stores backend types (KnowledgeQA/…) but some debug envelopes echo the
# frontend alias (chat/…). Accept both when verifying the probe receipt.
_MODEL_TYPE_ALIASES = {
    "KnowledgeQA": frozenset({"KnowledgeQA", "chat"}),
    "Embedding": frozenset({"Embedding", "embedding"}),
    "VLLM": frozenset({"VLLM", "vllm", "vision"}),
}

_PROBE_IMAGE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jLmQAAAAASUVORK5CYII="
)


def _require(condition):
    if not condition:
        raise ValueError("provider configuration or evidence unavailable")


def _segment(value):
    _require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value))
    return value


async def _instance(tenant):
    """The tenant's one ready WeKnora instance. With two, which one a space belongs to is ambiguous."""
    _require(type(tenant) is int and tenant > 0)
    _require(not is_tenant_filter_bypassed() and get_current_tenant_id() == tenant)
    async with get_async_db_session() as session:
        rows = (
            await session.execute(
                select(Instance.id, Instance.remote_scope_id, Instance.capability_revision).where(
                    Instance.tenant_id == tenant,
                    Instance.provider_key == "weknora",
                    Instance.state == "ready",
                )
            )
        ).all()
    _require(len(rows) == 1)
    id_, scope, revision = rows[0]
    _require(type(revision) is int and revision > 0 and isinstance(scope, str) and scope.isdigit())
    return Preset(tenant, id_, scope, revision, "", "", "", 1, 0)


def probe_budget_seconds() -> float:
    """A blocking remote model probe, in seconds.

    Read from the top-level ``weknora_probe_timeout_seconds`` so an operator can
    tune it without declaring a `weknora` instance block. Older blocks that put
    it under `weknora:` are still honoured, then the built-in default applies.
    """
    from bisheng.common.services.config_service import settings

    def usable(value):
        return value if type(value) in (int, float) and value > 0 else None

    read = usable(getattr(settings, "weknora_probe_timeout_seconds", None))
    if read is None:
        read = usable(getattr(getattr(settings, "weknora", None), "probe_timeout_seconds", None))
    return float(read or 180.0)


def probe_cache_seconds() -> float:
    """How long a successful model probe may be reused, in seconds. ``0`` disables reuse."""
    from bisheng.common.services.config_service import settings

    def usable(value):
        return value if type(value) in (int, float) and value >= 0 else None

    read = usable(getattr(settings, "weknora_model_probe_cache_seconds", None))
    if read is None:
        read = usable(getattr(getattr(settings, "weknora", None), "model_probe_cache_seconds", None))
    return float(300.0 if read is None else read)


# A probe is a full remote inference. Reusing a successful proof is what keeps
# the creation form responsive: editing a chunk size or switching a template must
# not re-prove models it never touched. Entries are keyed by the exact facts a
# proof asserts, so a different tenant, instance, scope, capability revision,
# model version or kind can never share one, and an expired entry is re-proved
# rather than trusted. The memory map is the per-process fast path; Redis is the
# shared one so a page reload, a second worker or a restart does not pay for the
# same inference again.
_probe_cache: dict[tuple, tuple[float, ModelProof]] = {}
# Only one inference per immutable key runs at a time; the other callers wait and
# then take the stored proof. Each caller keeps its own HTTP client, so a request
# that ends (or is cancelled) can never break another caller's probe.
_probe_locks: dict[tuple, asyncio.Lock] = {}
_PROBE_KEY_PREFIX = "bisheng:weknora:model-proof:"


def clear_probe_cache() -> None:
    """Test hook: forget every reusable probe."""
    _probe_cache.clear()
    _probe_locks.clear()


def _probe_key(p, model, kind) -> tuple:
    return (p.tenant_id, p.instance_id, p.scope, p.revision, model["id"], kind, model.get("name"))


def _proof_to_row(proof: ModelProof) -> dict:
    return {
        "model_id": proof.model_id,
        "kind": proof.kind,
        "version": proof.version,
        "instance_id": proof.instance_id,
        "scope": proof.scope,
        "available": proof.available,
        "dimension": proof.dimension,
        "images": proof.images,
    }


def _row_to_proof(row) -> ModelProof | None:
    if not isinstance(row, dict):
        return None
    try:
        proof = ModelProof(
            row["model_id"],
            row["kind"],
            row["version"],
            row["instance_id"],
            row["scope"],
            row["available"],
            row.get("dimension"),
            bool(row.get("images")),
        )
    except (KeyError, TypeError):
        return None
    # Reject a payload that would assert something different from what a probe proves.
    if (
        not isinstance(proof.model_id, str)
        or not proof.model_id
        or not isinstance(proof.version, str)
        or not proof.version
    ):
        return None
    if proof.available is not True or proof.kind not in ("chat", "embedding", "vision"):
        return None
    if proof.kind == "embedding" and (type(proof.dimension) is not int or proof.dimension <= 0):
        return None
    if proof.kind == "vision" and proof.images is not True:
        return None
    return proof


def _shared_probe_key(key: tuple) -> str:
    return _PROBE_KEY_PREFIX + digest(list(key))


async def _cached_proof(key: tuple, ttl: float) -> ModelProof | None:
    """A proof from this process, else from the shared cache. Never raises."""
    cached = _probe_cache.get(key)
    if cached is not None:
        expires, proof = cached
        if expires > time.monotonic():
            return proof
        _probe_cache.pop(key, None)
    if ttl <= 0:
        return None
    reloaded = await _shared_get(key)
    if reloaded is not None:
        _probe_cache[key] = (time.monotonic() + ttl, reloaded)
    return reloaded


async def _shared_get(key: tuple) -> ModelProof | None:
    try:
        from bisheng.core.cache.redis_manager import get_redis_client

        row = await (await get_redis_client()).aget(_shared_probe_key(key))
    except Exception:
        # A cache miss must never turn into a provisioning failure.
        logger.debug("weknora model proof cache unavailable", exc_info=True)
        return None
    return _row_to_proof(row)


async def _shared_put(key: tuple, proof: ModelProof, ttl: float) -> None:
    try:
        from bisheng.core.cache.redis_manager import get_redis_client

        await (await get_redis_client()).aset(_shared_probe_key(key), _proof_to_row(proof), expiration=max(1, int(ttl)))
    except Exception:
        logger.debug("weknora model proof cache write skipped", exc_info=True)


async def _probe_now(client, model, kind, p):
    """Always run a real inference and refresh the stored proof."""
    return await _probe_reusable(client, model, kind, p, fresh=True)


async def _probe_reusable(client, model, kind, p, *, fresh=False):
    """Probe one model, reusing an unexpired proof for the same immutable facts.

    ``fresh`` skips reuse. Creation uses it so the space is validated against
    what the provider serves right now, not against a cached preview.
    """
    key = _probe_key(p, model, kind)
    ttl = probe_cache_seconds()
    if not fresh:
        proof = await _cached_proof(key, ttl)
        if proof is not None:
            logger.info("weknora model probe reused id={} kind={}", model["id"], kind)
            return proof
    lock = _probe_locks.setdefault(key, asyncio.Lock())
    async with lock:
        # Whoever held the lock may have stored the proof while this caller waited.
        if not fresh:
            proof = await _cached_proof(key, ttl)
            if proof is not None:
                logger.info("weknora model probe reused id={} kind={}", model["id"], kind)
                return proof
        started = time.monotonic()
        proof = await _probe_model(client, model, kind, p.instance_id, p.scope)
        if ttl > 0:
            _probe_cache[key] = (time.monotonic() + ttl, proof)
            await _shared_put(key, proof, ttl)
        logger.info(
            "weknora model probe complete id={} kind={} elapsed={:.1f}s ttl={:.0f}s",
            model["id"],
            kind,
            time.monotonic() - started,
            ttl,
        )
        return proof


def _probe_timeout():
    """Transport timeout for the provisioning client (one probe per request)."""
    return httpx.Timeout(probe_budget_seconds(), connect=10.0)


async def _parameters(p):
    from bisheng.knowledge.application.provider_v1_runtime import _client_parameters

    _require(not is_tenant_filter_bypassed() and get_current_tenant_id() == p.tenant_id)
    async with get_async_db_session() as session:
        row = (
            await session.execute(
                select(Instance.endpoint, Instance.credential_ref, Instance.upload_credential_ref).where(
                    Instance.tenant_id == p.tenant_id,
                    Instance.id == p.instance_id,
                    Instance.provider_key == "weknora",
                    Instance.remote_scope_id == p.scope,
                    Instance.capability_revision == p.revision,
                    Instance.state == "ready",
                )
            )
        ).one_or_none()
    _require(row is not None)
    endpoint, credential_ref, upload_ref = row
    params = _client_parameters(
        endpoint,
        credential_ref,
        tenant_id=p.tenant_id,
        instance_id=p.instance_id,
        scope=p.scope,
        timeout=_probe_timeout(),
    )
    return params, upload_ref


def _extract_source(selection):
    _require(selection is not None)
    template = selection.extract_template_kb_id
    config = selection.extract_config.as_weknora() if selection.extract_config is not None else None
    _require((template is None) != (config is None))
    if template is not None:
        _segment(template)
    return template, config


async def load_preset(tenant_id: int, selection) -> Preset:
    template, config = _extract_source(selection)
    preset = replace(
        await _instance(tenant_id),
        summary=selection.summary_model_id,
        embedding=selection.embedding_model_id,
        vision=selection.vision_model_id,
        chunk_size=selection.chunk_size,
        overlap=selection.overlap,
        extract_template_kb_id=template,
        extract_config=config,
    )
    _require(type(preset.chunk_size) is int and type(preset.overlap) is int and 0 <= preset.overlap < preset.chunk_size)
    _require(len({_segment(i) for i in (preset.summary, preset.embedding, preset.vision)}) == 3)
    await _parameters(preset)
    return preset


_MODEL_KINDS = {"KnowledgeQA": "chat", "Embedding": "embedding", "VLLM": "vision"}


async def list_models(tenant_id: int) -> dict:
    """Candidates for the creator to pick from; each pick is still probed before the space is created."""
    p = await _instance(tenant_id)
    async with _client(p) as client:
        rows = await _data(client, "GET", "models")
    _require(isinstance(rows, list))
    found = {kind: [] for kind in _MODEL_KINDS.values()}
    for m in rows:
        kind = _MODEL_KINDS.get(m.get("type"))
        name = m.get("name")
        if kind is None or str(m.get("tenant_id")) != p.scope or not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(m.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", m["id"]):
            continue
        item = {"id": m["id"], "name": name, "display_name": m.get("display_name") or name}
        if kind == "embedding":
            dimension = ((m.get("parameters") or {}).get("embedding_parameters") or {}).get("dimension")
            if type(dimension) is not int or dimension <= 0:
                continue
            item["dimension"] = dimension
        found[kind].append(item)
    return found


def _extract_usable(extract) -> bool:
    if not isinstance(extract, dict) or extract.get("enabled") is not True:
        return False
    text, tags, nodes, relations = (
        extract.get("text"),
        extract.get("tags"),
        extract.get("nodes"),
        extract.get("relations"),
    )
    if not isinstance(text, str) or not text.strip() or not isinstance(tags, list) or not tags or not all(tags):
        return False
    if not isinstance(nodes, list) or not nodes:
        return False
    names = []
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("name"), str) or not node["name"].strip():
            return False
        names.append(node["name"])
    if len(set(names)) != len(names):
        return False
    known = set(names)
    if not isinstance(relations, list) or not relations:
        return False
    for rel in relations:
        if (
            not isinstance(rel, dict)
            or rel.get("node1") not in known
            or rel.get("node2") not in known
            or not isinstance(rel.get("type"), str)
            or not rel["type"].strip()
        ):
            return False
    return True


async def list_extract_templates(tenant_id: int) -> list:
    """WeKnora knowledge bases in this scope whose extract_config is enabled and structurally usable."""
    p = await _instance(tenant_id)
    async with _client(p) as client:
        rows = await _data(client, "GET", "knowledge-bases")
    _require(isinstance(rows, list))
    found = []
    for kb in rows:
        id_, name = kb.get("id"), kb.get("name")
        if str(kb.get("tenant_id")) != p.scope:
            continue
        if not isinstance(id_, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", id_):
            continue
        if not isinstance(name, str) or not name.strip() or not _extract_usable(kb.get("extract_config")):
            continue
        found.append({"id": id_, "name": name})
    return found


@asynccontextmanager
async def _client(p):
    from bisheng.knowledge.application.provider_v1_runtime import _attach_external_identity

    params, upload_ref = await _parameters(p)
    async with httpx.AsyncClient(**_attach_external_identity(params, upload_ref, p.scope)) as client:
        yield client


def _envelope_ok(body) -> bool:
    """WeKnora mixes two envelopes: success=true (most routes) and code=0 (system/info)."""
    if not isinstance(body, dict) or not isinstance(body.get("data"), (list, dict)):
        return False
    if body.get("success") is True:
        return True
    code = body.get("code")
    return code == 0 or code == "0"


async def _data(client, method, path, **kwargs):
    started = time.monotonic()
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.TimeoutException as exc:
        # Name the call and its budget: a silent "receipt unavailable" here has
        # been misread as a provider outage when it was really a slow model probe.
        logger.warning(
            "weknora {} {} timed out after {:.1f}s timeout={!r}",
            method,
            path.split("/")[0],
            time.monotonic() - started,
            client.timeout,
        )
        raise ConnectionError("provider receipt unavailable") from exc
    except httpx.TransportError as exc:
        # A dropped response does not distinguish rollback from committed write.
        raise ConnectionError("provider receipt unavailable") from exc
    if response.status_code == httpx.codes.NOT_FOUND:
        raise ProviderTargetAbsent("provider target not found")
    _require(200 <= response.status_code < 300)
    body = response.json()
    _require(_envelope_ok(body))
    return body["data"]


def _model_type_ok(actual, expected) -> bool:
    return str(actual or "") in _MODEL_TYPE_ALIASES.get(expected, frozenset({expected}))


def _debug_error_hint(data) -> str:
    err = data.get("error") if isinstance(data, dict) else None
    if not isinstance(err, str) or not err.strip():
        return ""
    # Truncate; never log credentials that might appear in upstream error text.
    text = re.sub(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*\S+", r"\1=[REDACTED]", err.strip())
    return text[:240]


async def _debug(client, id_, *, input_text, options, image):
    payload = {"input": input_text}
    if options is not None:
        payload["options"] = options
    kwargs = {"files": {"file": ("canary.png", _PROBE_IMAGE, "image/png")}} if image else {}
    return await _data(client, "POST", f"models/{id_}/debug", data=payload, **kwargs)


# A reasoning model answers the probe in tens of seconds unless the answer is
# capped. `options` is WeKnora's own debug contract (max_tokens/thinking); a
# vendor that rejects it is probed again without it, so the receipt is never
# weakened by an option the model cannot honour.
_PROBE_OPTIONS = '{"max_tokens": 32, "thinking": false}'


async def _probe_model(client, model, kind, instance, scope):
    id_ = _segment(model["id"])
    vendor_type = {"embedding": "Embedding", "chat": "KnowledgeQA", "vision": "VLLM"}[kind]
    # The upstream model name is what WeKnora actually calls; editing keys or limits keeps it.
    version = model.get("name")
    _require(
        str(model["tenant_id"]) == scope
        and _model_type_ok(model.get("type"), vendor_type)
        and isinstance(version, str)
        and version.strip()
    )
    input_text = "Describe the pixel." if kind == "vision" else "BiSheng health check"
    image = kind == "vision"
    started = time.monotonic()
    # Embeddings are fast already; capping generation only concerns chat/vision.
    options = None if kind == "embedding" else _PROBE_OPTIONS
    data = await _debug(client, id_, input_text=input_text, options=options, image=image)
    if options is not None and data.get("ok") is not True:
        logger.info("weknora model probe retry without options id={} kind={}", id_, kind)
        data = await _debug(client, id_, input_text=input_text, options=None, image=image)
    elapsed = time.monotonic() - started
    req = data.get("request") if isinstance(data.get("request"), dict) else {}
    ok = data.get("ok") is True
    id_ok = req.get("model_id") == id_
    type_ok = _model_type_ok(req.get("model_type"), vendor_type)
    if not (ok and id_ok and type_ok):
        logger.warning(
            "weknora model debug reject id={} kind={} elapsed={:.1f}s ok={} id_match={} type={!r} expected={} hint={}",
            id_,
            kind,
            elapsed,
            data.get("ok"),
            id_ok,
            req.get("model_type"),
            vendor_type,
            _debug_error_hint(data),
        )
    _require(ok and id_ok and type_ok)
    raw = data["raw_response"]
    dimension = None
    if kind == "embedding":
        dimension = model["parameters"]["embedding_parameters"]["dimension"]
        _require(
            type(dimension) is int
            and dimension > 0
            and isinstance(raw, list)
            and len(raw) == dimension
            and data["observations"]["dimension"] == dimension
            and all(type(v) in (float, int) and math.isfinite(v) for v in raw)
        )
    else:
        answer = raw["content"] if kind == "chat" else raw
        _require(isinstance(answer, str) and answer.strip())
        if kind == "vision":
            _require(data["request"]["file"]["size"] == len(_PROBE_IMAGE))
    return ModelProof(id_, kind, version, instance, scope, True, dimension, kind == "vision")


def _target(op):
    """An existing space or operation addresses the instance it was frozen on, not today's preset."""
    return Preset(op.tenant_id, op.provider_instance_id, op.remote_scope_id, op.capability_revision, "", "", "", 1, 0)


async def _kb(client, kb_id, scope):
    kb = await _data(client, "GET", "knowledge-bases/" + _segment(kb_id))
    _require(kb["id"] == kb_id and str(kb["tenant_id"]) == scope)
    return kb


async def _models(client, p, uses, rows=None, *, reuse=True):
    if rows is None:
        rows = await _data(client, "GET", "models")
    _require(isinstance(rows, list))
    targets = {}
    for id_, kind in uses:
        matches = [m for m in rows if m.get("id") == id_ and str(m.get("tenant_id")) == p.scope]
        _require(len(matches) == 1)
        targets[id_] = (matches[0], kind)
    # Probes block on a full inference each; run them together so one space
    # preview costs the slowest model rather than the sum of all of them.
    # return_exceptions=True keeps a second failure from becoming an unretrieved
    # task exception; the first one is re-raised below in declaration order.
    # A preview may reuse an unexpired proof; a create never does.
    probe = _probe_reusable if reuse else _probe_now
    results = await asyncio.gather(
        *(probe(client, model, kind, p) for model, kind in targets.values()),
        return_exceptions=True,
    )
    proofs = {}
    for id_, result in zip(targets, results, strict=True):
        if isinstance(result, BaseException):
            raise result
        proofs[id_] = result
    return proofs


async def _resolve_extract(client, p, *, reuse=True):
    """Read everything a preset asserts: model proofs plus the copied extraction rules.

    The three cheap reads are independent, so they run together; only the model
    proofs (a full remote inference each) are slow. A preview may reuse an
    unexpired proof; a create passes ``reuse=False`` and re-proves.
    """
    template_id = p.extract_template_kb_id
    reads = await asyncio.gather(
        _data(client, "GET", "system/info"),
        _data(client, "GET", "models"),
        *([_kb(client, template_id, p.scope)] if template_id else []),
    )
    info, rows = reads[0], reads[1]
    # Handler reports "Neo4j"; some builds historically used lowercase "neo4j".
    _require(str(info.get("graph_database_engine") or "").casefold() == "neo4j")
    extract = reads[2]["extract_config"] if template_id else p.extract_config
    _require(_extract_usable(extract))
    models = await _models(
        client, p, [(p.summary, "chat"), (p.embedding, "embedding"), (p.vision, "vision")], rows, reuse=reuse
    )
    proof = PresetProof(
        models,
        True,
        extract["text"],
        tuple(extract["tags"]),
        tuple(n["name"] for n in extract["nodes"]),
        tuple((r["node1"], r["type"], r["node2"]) for r in extract["relations"]),
        digest(extract),
    )
    return proof, extract


class ProvisionRemote:
    async def probe_preset(self, preset):
        async with _client(preset) as client:
            proof, _ = await _resolve_extract(client, preset)
            return proof

    async def probe_settings(self, target, patch):
        p = _target(target)
        async with _client(p) as client:
            kb = await _kb(client, target.remote_kb_id, p.scope)
            version = kb.get("settings_version")
            _require(kb.get("model_policy") == "bisheng-v1" and type(version) is int and version >= 0)
            uses = [
                (_segment(v), "vision" if k == "vision_model_id" else "chat") for k, v in patch.items() if v is not None
            ]
            return await _models(client, p, uses), version

    async def patch_library(self, op, patch):
        p = _target(op)
        async with _client(p) as client:
            await _data(
                client,
                "PUT",
                f"knowledge-bases/{_segment(op.remote_kb_id)}/managed-settings",
                json={
                    "operation_id": _segment(op.operation_id),
                    "patch": patch,
                    "digest": digest(patch),
                    "expected_version": op.target_manifest[0]["expected_remote_version"],
                },
            )

    async def create_library(self, op, name, config):
        item = op.target_manifest[0]
        p = replace(
            _target(op),
            summary=config["summary_model_id"],
            embedding=config["embedding_model_id"],
            vision=config["vision_model_id"],
            chunk_size=config["chunk_size"],
            overlap=config["overlap"],
            extract_template_kb_id=item.get("extract_template_kb_id"),
            extract_config=item.get("extract_config"),
        )
        _require((p.extract_template_kb_id is None) != (p.extract_config is None))
        async with _client(p) as client:
            # A template edited after the creator confirmed the summary changes its digest; refuse that copy.
            # Creation always re-proves: a cached preview must not stand in for the current provider state.
            proof, extract = await _resolve_extract(client, p, reuse=False)
            _require(preflight(p, proof) == config)
            await _data(
                client,
                "POST",
                "knowledge-bases",
                json={
                    "id": _segment(op.remote_kb_id),
                    "name": name,
                    "type": "document",
                    "model_policy": "bisheng-v1",
                    "summary_model_id": p.summary,
                    "embedding_model_id": p.embedding,
                    "vlm_config": {"enabled": True, "model_id": p.vision},
                    "chunking_config": {"chunk_size": p.chunk_size, "chunk_overlap": p.overlap},
                    "indexing_strategy": {
                        "vector_enabled": True,
                        "keyword_enabled": True,
                        "wiki_enabled": True,
                        "graph_enabled": True,
                    },
                    "extract_config": extract,
                    "auto_tag_config": {"enabled": True},
                },
            )

    async def read_library(self, op):
        p = _target(op)
        async with _client(p) as client:
            kb = await _kb(client, op.remote_kb_id, p.scope)
            emb, summary, vision = kb["embedding_model_id"], kb["summary_model_id"], kb["vlm_config"]["model_id"]
            proof = await _models(client, p, [(emb, "embedding"), (summary, "chat"), (vision, "vision")])
        idx, chunk, extract = kb["indexing_strategy"], kb["chunking_config"], kb["extract_config"]
        _require(extract is not None)
        # Managed create always sends model_policy=bisheng-v1. Some WeKnora builds accept
        # the field on create but omit/empty it on GET — including settings reads via
        # ActiveTarget (no create target_manifest). Only this ProvisionRemote path reads
        # BiSheng-bound libraries, so treat missing/empty as the managed policy.
        policy = kb.get("model_policy") or "bisheng-v1"
        _require(policy == "bisheng-v1")
        config = {
            "type": kb["type"],
            "model_policy": policy,
            "preset_revision": p.revision,
            "embedding_model_id": emb,
            "embedding_dimension": proof[emb].dimension,
            "embedding_version": proof[emb].version,
            "summary_model_id": summary,
            "summary_version": proof[summary].version,
            "vision_model_id": vision,
            "vision_version": proof[vision].version,
            "chunk_size": chunk["chunk_size"],
            "overlap": chunk["chunk_overlap"],
            "extract_digest": digest(extract),
            "wiki_model_id": (kb["wiki_config"] or {}).get("synthesis_model_id") or None,
            "tag_model_id": kb["auto_tag_config"].get("model_id") or None,
            "auto_tag_enabled": kb["auto_tag_config"]["enabled"],
            "wiki_enabled": idx["wiki_enabled"],
            "entities_enabled": idx["graph_enabled"] is True and extract["enabled"] is True,
            "multimodal_enabled": kb["vlm_config"]["enabled"],
            "keyword_index_enabled": idx["keyword_enabled"],
            "vector_index_enabled": idx["vector_enabled"],
        }
        return {
            "kb_id": kb["id"],
            "settings_version": kb.get("settings_version"),
            "settings_digest": kb.get("settings_digest"),
            "applied_operation_id": kb.get("applied_operation_id"),
            "scope": str(kb["tenant_id"]),
            "instance_id": p.instance_id,
            "name": kb["name"],
            "config": config,
        }


async def build_provisioning(login_user) -> ProviderProvisioning:
    from bisheng.admin.application.tenant_scope import resolve_management_scope
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.database.models.role_access import WebMenuResource
    from bisheng.knowledge.domain.services.department_knowledge_space_service import (
        DepartmentKnowledgeSpaceService as Dept,
    )
    from bisheng.permission.application.business_authorization import check_business_action
    from bisheng.permission.application.identity import is_current_tenant_administrator

    async def authorize(tenant, actor, action, resource):
        if actor != login_user.user_id or get_current_tenant_id() != tenant or is_tenant_filter_bypassed():
            return False
        scope = await resolve_management_scope(
            actor, is_super=login_user.is_global_super, for_write=action != "read_settings"
        )
        if scope.tenant_id != tenant:
            return False
        if action == "create_department":
            await Dept._ensure_tenant_admin(login_user)
            return resource in await Dept._load_departments([resource])
        if action == "create_personal":
            if not login_user.is_global_super and not await is_current_tenant_administrator(login_user):
                await UserPayload.assert_effective_web_menu_contains(actor, WebMenuResource.CREATE_KNOWLEDGE.value)
            return True
        if action not in ("read_settings", "manage_settings"):
            return False
        return await check_business_action(
            login_user,
            resource_type="knowledge_space",
            resource_id=resource,
            action="visible" if action == "read_settings" else "manage_permission",
        )

    async def project(op):
        return await Dept.project_external_space(op, request=None, login_user=login_user)

    return ProviderProvisioning(ProvisionRepository(), ProvisionRemote(), authorize, project)


def register_provision_handlers(registry, handler_type):
    def step(name):
        async def execute(op):
            from bisheng.user.application.runtime_identity import resolve_preview_person

            person = await resolve_preview_person(op.actor_user_id)
            app = await build_provisioning(person)
            return await getattr(app, name)(op)

        return execute

    handlers = handler_type(*(step(s) for s in ("send", "reconcile", "project")))
    registry.update(create_space=handlers, update_space_settings=handlers)
