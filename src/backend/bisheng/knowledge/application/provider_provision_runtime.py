"""F026 provisioning composition. No instance, preset or model is implicit.

weknora.deployment in the backend YAML (or legacy BS_WEKNORA_PRESET_<tenant> JSON) contains: preset (Preset fields),
model_pins (model id -> immutable version and matching directory updated_at),
template_id and extract_digest (verified upstream template), graph_verified_at
(UTC epoch of the last successful same-instance/revision graph canary).
A declared graph engine or a model directory status alone is not a proof.
"""

import base64
import json
import math
import os
import re
import time
from contextlib import asynccontextmanager

import httpx
from sqlalchemy import select

from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.provider_provisioning import (
    ModelProof,
    Preset,
    PresetProof,
    ProviderProvisioning,
    digest,
    preflight,
)
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderInstance as Instance
from bisheng.knowledge.domain.repositories.provider_provision_repository import ProvisionRepository

_PROBE_IMAGE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jLmQAAAAASUVORK5CYII="
)


def _require(condition):
    if not condition:
        raise ValueError("provider configuration or evidence unavailable")


def _segment(value):
    _require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value))
    return value


def _deployment(tenant):
    from bisheng.common.services.config_service import settings

    _require(type(tenant) is int and tenant > 0)
    cfg = settings.weknora
    try:
        use_yaml = cfg is not None and cfg.tenant_id == tenant and cfg.deployment is not None
        doc = cfg.deployment if use_yaml else json.loads(os.environ[f"BS_WEKNORA_PRESET_{tenant}"])
        p = Preset(**doc["preset"])
        if use_yaml:
            _require((p.instance_id, p.scope) == (cfg.instance_id, cfg.remote_scope_id))
        _require(
            type(p.tenant_id) is int
            and p.tenant_id == tenant
            and type(p.instance_id) is int
            and p.instance_id > 0
            and type(p.revision) is int
            and p.revision > 0
            and isinstance(p.scope, str)
            and p.scope.isdigit()
        )
        _require(type(p.chunk_size) is int and type(p.overlap) is int and 0 <= p.overlap < p.chunk_size)
        _require(len({_segment(i) for i in (p.summary, p.embedding, p.vision)}) == 3)
        _segment(doc["template_id"])
        _require(re.fullmatch("[a-f0-9]{64}", doc["extract_digest"]))
        return p, doc
    except (KeyError, TypeError, ValueError):
        raise ValueError("missing or invalid trusted provisioning deployment") from None


async def _parameters(p):
    from bisheng.knowledge.application.provider_v1_runtime import _client_parameters

    _require(not is_tenant_filter_bypassed() and get_current_tenant_id() == p.tenant_id)
    async with get_async_db_session() as session:
        row = (
            await session.execute(
                select(Instance.endpoint, Instance.credential_ref).where(
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
    return _client_parameters(*row, tenant_id=p.tenant_id, instance_id=p.instance_id, scope=p.scope)


async def load_preset(tenant_id: int) -> Preset:
    preset, _ = _deployment(tenant_id)
    await _parameters(preset)
    return preset


@asynccontextmanager
async def _client(p):
    async with httpx.AsyncClient(**await _parameters(p)) as client:
        yield client


async def _data(client, method, path, **kwargs):
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.TransportError as exc:
        # A dropped response does not distinguish rollback from committed write.
        raise ConnectionError("provider receipt unavailable") from exc
    _require(200 <= response.status_code < 300)
    body = response.json()
    _require(isinstance(body, dict) and body.get("success") is True and isinstance(body.get("data"), (list, dict)))
    return body["data"]


async def _probe_model(client, model, kind, instance, scope, pin):
    id_ = _segment(model["id"])
    vendor_type = {"embedding": "Embedding", "chat": "KnowledgeQA", "vision": "VLLM"}[kind]
    _require(
        str(model["tenant_id"]) == scope
        and model["type"] == vendor_type
        and pin.get("updated_at")
        and pin["updated_at"] == model["updated_at"]
        and isinstance(pin.get("version"), str)
        and pin["version"].strip()
    )
    kwargs = {"files": {"file": ("canary.png", _PROBE_IMAGE, "image/png")}} if kind == "vision" else {}
    data = await _data(
        client,
        "POST",
        f"models/{id_}/debug",
        data={"input": "Describe the pixel." if kind == "vision" else "BiSheng health check"},
        **kwargs,
    )
    _require(data["ok"] is True and data["request"]["model_id"] == id_ and data["request"]["model_type"] == vendor_type)
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
    return ModelProof(id_, kind, pin["version"], instance, scope, True, dimension, kind == "vision")


def _target(op):
    p, doc = _deployment(op.tenant_id)
    _require(
        (p.instance_id, p.scope, p.revision) == (op.provider_instance_id, op.remote_scope_id, op.capability_revision)
    )
    return p, doc


async def _kb(client, kb_id, scope):
    kb = await _data(client, "GET", "knowledge-bases/" + _segment(kb_id))
    _require(kb["id"] == kb_id and str(kb["tenant_id"]) == scope)
    return kb


async def _models(client, p, doc, uses):
    rows = await _data(client, "GET", "models")
    _require(isinstance(rows, list))
    proofs = {}
    for id_, kind in uses:
        matches = [m for m in rows if m.get("id") == id_ and str(m.get("tenant_id")) == p.scope]
        _require(len(matches) == 1 and id_ in doc["model_pins"])
        proofs[id_] = await _probe_model(client, matches[0], kind, p.instance_id, p.scope, doc["model_pins"][id_])
    return proofs


async def _template(client, p, doc):
    stamp = doc.get("graph_verified_at")
    _require(type(stamp) in (int, float) and 0 <= time.time() - stamp <= 300)
    info = await _data(client, "GET", "system/info")
    _require(info.get("graph_database_engine") == "Neo4j")
    kb = await _kb(client, doc["template_id"], p.scope)
    extract = kb["extract_config"]
    _require(extract["enabled"] is True and digest(extract) == doc["extract_digest"])
    models = await _models(client, p, doc, [(p.summary, "chat"), (p.embedding, "embedding"), (p.vision, "vision")])
    proof = PresetProof(
        models,
        True,
        extract["text"],
        tuple(extract["tags"]),
        tuple(n["name"] for n in extract["nodes"]),
        tuple((r["node1"], r["type"], r["node2"]) for r in extract["relations"]),
    )
    return proof, extract


class ProvisionRemote:
    async def probe_preset(self, preset):
        p, doc = _deployment(preset.tenant_id)
        _require(
            (p.instance_id, p.scope, p.revision) == (preset.instance_id, preset.scope, preset.revision)
            and p.vision == preset.vision
            and p.chunk_size == preset.chunk_size
            and p.overlap == preset.overlap
        )
        async with _client(p) as client:
            proof, _ = await _template(client, preset, doc)
            return proof

    async def probe_settings(self, target, patch):
        p, doc = _target(target)
        async with _client(p) as client:
            kb = await _kb(client, target.remote_kb_id, p.scope)
            version = kb.get("settings_version")
            _require(kb.get("model_policy") == "bisheng-v1" and type(version) is int and version >= 0)
            uses = [
                (_segment(v), "vision" if k == "vision_model_id" else "chat") for k, v in patch.items() if v is not None
            ]
            return await _models(client, p, doc, uses), version

    async def patch_library(self, op, patch):
        p, _ = _target(op)
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
        from dataclasses import replace

        p, doc = _target(op)
        p = replace(p, summary=config["summary_model_id"], embedding=config["embedding_model_id"])
        async with _client(p) as client:
            proof, extract = await _template(client, p, doc)
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
        p, doc = _target(op)
        async with _client(p) as client:
            kb = await _kb(client, op.remote_kb_id, p.scope)
            emb, summary, vision = kb["embedding_model_id"], kb["summary_model_id"], kb["vlm_config"]["model_id"]
            proof = await _models(client, p, doc, [(emb, "embedding"), (summary, "chat"), (vision, "vision")])
        idx, chunk, extract = kb["indexing_strategy"], kb["chunking_config"], kb["extract_config"]
        _require(extract is not None and digest(extract) == doc["extract_digest"])
        _require(kb.get("model_policy") == "bisheng-v1")
        config = {
            "type": kb["type"],
            "model_policy": kb["model_policy"],
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
