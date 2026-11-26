"""External space provisioning. All admission facts except the expected tenant,
selection and displayed summary must come from trusted server-side owners.
No Native indexing, routing, or implicit default provider is used here.
"""

import json
import re
from dataclasses import asdict, dataclass
from hashlib import sha256


class ProviderTargetAbsent(ValueError):
    """The addressed remote object definitively does not exist (HTTP 404).

    Distinct from a generic failure on purpose: a create that addressed an
    explicit remote id may be replayed when the target is proven absent, while
    any other error stays "unknown" so a possibly-committed write is never
    repeated.
    """


@dataclass(frozen=True)
class ModelProof:
    """Current successful controlled probe (not model-directory status)."""

    model_id: str
    kind: str
    version: str
    instance_id: int
    scope: str
    available: bool
    dimension: int | None = None
    images: bool = False


@dataclass(frozen=True)
class Preset:
    """Server-resolved, immutable verified environment preset revision."""

    tenant_id: int
    instance_id: int
    scope: str
    revision: int
    summary: str
    embedding: str
    vision: str
    chunk_size: int
    overlap: int
    # Exactly one extract source: a WeKnora KB to copy, or a creator-supplied config.
    extract_template_kb_id: str | None = None
    extract_config: dict | None = None


@dataclass(frozen=True)
class SpaceSpec:
    name: str
    department_id: int | None = None
    description: str | None = None
    icon: str | None = None
    auth_type: str = "private"
    is_released: bool = False

    def __post_init__(self):
        if not self.name.strip() or len(self.name) > 200 or self.auth_type not in {"public", "private", "approval"}:
            raise ValueError("invalid space name or sharing mode")
        if self.department_id is not None and (type(self.department_id) is not int or self.department_id <= 0):
            raise ValueError("invalid department")


def digest(value):
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def create_item_key(request_key, department_id):
    """Stable per-item identity shared by admission, replay and read-only status."""
    return digest([request_key, department_id])


def _model(models, id_, kind, instance, scope):
    m = models.get(id_)
    if (
        not id_
        or not m
        or m.model_id != id_
        or m.kind != kind
        or m.instance_id != instance
        or m.scope != scope
        or not m.version
        or m.available is not True
        or (kind == "vision" and m.images is not True)
        or (kind == "embedding" and (type(m.dimension) is not int or m.dimension <= 0))
    ):
        raise ValueError(f"{kind} model {id_!r}: unavailable, wrong scope or incompatible")
    return m


@dataclass(frozen=True)
class PresetProof:
    """Fresh server-side environment probe; extraction examples stay remote."""

    models: dict[str, ModelProof]
    graph_available: bool
    sample_text: str
    tags: tuple[str, ...]
    nodes: tuple[str, ...]
    relations: tuple[tuple[str, str, str], ...]  # source, type, target
    extract_digest: str  # of the extract_config this probe read; the space keeps it


def preflight(preset, proof):
    if not isinstance(proof, PresetProof) or proof.graph_available is not True:
        raise ValueError("graph dependency unavailable")
    if (
        not proof.sample_text.strip()
        or not proof.tags
        or not all(proof.tags)
        or not proof.nodes
        or not all(proof.nodes)
        or len(set(proof.nodes)) != len(proof.nodes)
        or not proof.relations
        or not all(source in proof.nodes and kind and target in proof.nodes for source, kind, target in proof.relations)
        or not re.fullmatch("[a-f0-9]{64}", proof.extract_digest or "")
    ):
        raise ValueError("invalid entity extraction preset")
    models = proof.models
    if not (0 <= preset.overlap < preset.chunk_size) or preset.revision <= 0:
        raise ValueError("invalid chunking or unverified preset revision")
    config = {
        "type": "document",
        "model_policy": "bisheng-v1",
        "vector_index_enabled": True,
        "keyword_index_enabled": True,
        "preset_revision": preset.revision,
        "chunk_size": preset.chunk_size,
        "overlap": preset.overlap,
        "extract_digest": proof.extract_digest,
        "wiki_enabled": True,
        "entities_enabled": True,
        "multimodal_enabled": True,
        "auto_tag_enabled": True,
        "wiki_model_id": None,
        "tag_model_id": None,
    }
    for use, kind in [("summary", "chat"), ("embedding", "embedding"), ("vision", "vision")]:
        m = _model(models, getattr(preset, use), kind, preset.instance_id, preset.scope)
        config[f"{use}_model_id"] = m.model_id
        config[f"{use}_version"] = m.version
        if use == "embedding":
            config["embedding_dimension"] = m.dimension
    return config


class ProviderProvisioning:
    """Bound remote port reads *normalized* facts only. Its model probe resolves
    the immutable preset, validates extraction examples/dependencies and must
    fail if unavailable. Authorization/projector are mandatory permission-owner
    ports. Neither a transport ACK nor an unverified projection releases a binding.
    """

    def __init__(self, repo, remote, authorize, project_grants):
        self.repo, self.remote, self.authorize, self.project_grants = repo, remote, authorize, project_grants

    async def _allowed(self, tenant, actor, action, resource):
        if await self.authorize(tenant, actor, action, resource) is not True:
            raise PermissionError("space action denied")

    @staticmethod
    def _scope(tenant, expected):
        if type(expected) is not int or expected != tenant or expected <= 0:
            raise PermissionError("management tenant changed")

    async def preview(self, *, tenant_id, actor, space, preset):
        from bisheng.knowledge.application.provider_external_token import provider_external_identity

        self._scope(tenant_id, preset.tenant_id)
        await self._allowed(
            tenant_id, actor, "create_department" if space.department_id else "create_personal", space.department_id
        )
        with provider_external_identity(actor):
            return preflight(preset, await self.remote.probe_preset(preset))

    async def create(self, *, tenant_id, expected_tenant, actor, key, space, preset, summary):
        from bisheng.knowledge.application.provider_external_token import provider_external_identity

        self._scope(tenant_id, expected_tenant)
        self._scope(tenant_id, preset.tenant_id)
        if not key:
            raise ValueError("request key required")
        # Per-department key; changing the batch selection cannot shift item identity.
        item_key = create_item_key(key, space.department_id)
        identity = digest([asdict(space), asdict(preset), summary])
        await self._allowed(
            tenant_id, actor, "create_department" if space.department_id else "create_personal", space.department_id
        )
        replay = await self.repo.replay(tenant_id, "create_space", item_key, actor, identity)
        if replay is not None:
            return replay
        with provider_external_identity(actor):
            config = preflight(preset, await self.remote.probe_preset(preset))
        if config != summary:
            raise ValueError("displayed model or preset revision changed")
        op = await self.repo.reserve_create(preset, space, actor, item_key, identity, config)
        # Committed intent is dispatchable right away. The periodic sweep remains
        # the safety net for a broker that is down; the request already succeeded.
        from bisheng.worker.knowledge.provider_operations import wake_provider_operation

        if op.state in ("pending",):
            wake_provider_operation(tenant_id=op.tenant_id, operation_id=op.operation_id, expected_revision=op.revision)
        return op

    async def read_settings(self, *, tenant_id, actor, space_id):
        from bisheng.knowledge.application.provider_external_token import provider_external_identity

        await self._allowed(tenant_id, actor, "read_settings", space_id)
        target = await self.repo.active_target(tenant_id, space_id)
        with provider_external_identity(actor):
            observed = await self.remote.read_library(target)
        if not self._matches(target, observed):
            raise ValueError("unverified settings read")
        return {"revision": target.revision, "settings": observed["config"], "pending": target.pending}

    async def settings(self, *, tenant_id, expected_tenant, actor, space_id, key, expected_revision, patch):
        from bisheng.knowledge.application.provider_external_token import provider_external_identity

        self._scope(tenant_id, expected_tenant)
        await self._allowed(tenant_id, actor, "manage_settings", space_id)
        allowed = {"summary_model_id", "wiki_model_id", "tag_model_id", "vision_model_id"}
        if not key or not patch or patch.keys() - allowed:
            raise ValueError("unsupported settings change")
        identity = digest([space_id, expected_revision, patch])
        replay = await self.repo.replay(tenant_id, "update_space_settings", key, actor, identity)
        if replay is not None:
            return replay
        target = await self.repo.active_target(tenant_id, space_id)
        if expected_revision != target.revision or target.pending:
            raise ValueError("settings revision or pending write conflict")
        with provider_external_identity(actor):
            models, version = await self.remote.probe_settings(target, patch)
        if type(version) is not int or not 0 <= version < 2**53 - 1:
            raise ValueError("unverified remote settings version")
        for field, value in patch.items():
            if value is None and field in {"wiki_model_id", "tag_model_id"}:
                continue
            _model(
                models,
                value,
                "vision" if field == "vision_model_id" else "chat",
                target.provider_instance_id,
                target.remote_scope_id,
            )
        op = await self.repo.reserve_settings(target, actor, key, identity, dict(patch), version)
        from bisheng.worker.knowledge.provider_operations import wake_provider_operation

        if op.state in ("pending",):
            wake_provider_operation(tenant_id=op.tenant_id, operation_id=op.operation_id, expected_revision=op.revision)
        return op

    @staticmethod
    def _matches(op, observed):
        return bool(
            observed
            and observed.get("instance_id") == op.provider_instance_id
            and observed.get("scope") == op.remote_scope_id
            and observed.get("kb_id") == op.remote_kb_id
            and isinstance(observed.get("config"), dict)
        )

    async def send(self, op):
        from bisheng.knowledge.application.provider_external_token import provider_external_identity

        await self.repo.require_send_target(op)
        f = op.target_manifest[0]
        try:
            with provider_external_identity(op.actor_user_id):
                if op.kind == "create_space":
                    await self._allowed(
                        op.tenant_id,
                        op.actor_user_id,
                        "create_department" if f["department_id"] else "create_personal",
                        f["department_id"],
                    )
                    await self.remote.create_library(op, f["name"], f["config"])
                elif op.kind == "update_space_settings":
                    await self._allowed(op.tenant_id, op.actor_user_id, "manage_settings", op.space_id)
                    await self.remote.patch_library(op, f["patch"])
                else:
                    raise ValueError("not a provisioning operation")
        except (TimeoutError, ConnectionError):
            return "unknown"
        return await self.reconcile(op)

    async def reconcile(self, op):
        from bisheng.knowledge.application.provider_external_token import provider_external_identity

        try:
            with provider_external_identity(op.actor_user_id):
                observed = await self.remote.read_library(op)
        except (TimeoutError, ConnectionError):
            return "unknown"
        except ProviderTargetAbsent:
            # The library is provably not there. A create addresses an explicit
            # remote id, so re-sending it cannot duplicate anything; anything
            # else would be repeating a write against a target we cannot see.
            if op.kind == "create_space":
                return "verified_safe_replay"
            raise
        if not self._matches(op, observed):
            return "unknown"
        f = op.target_manifest[0]
        if op.kind == "create_space":
            if observed.get("name") != f["name"]:
                return "unknown"
            expected = f["config"]
        elif op.kind == "update_space_settings":
            # Reading an old (or coincidentally equal) value is not evidence
            # that the in-flight write has finished. Require its own receipt.
            if (
                observed.get("applied_operation_id") != op.operation_id
                or observed.get("settings_digest") != digest(f["patch"])
                or type(f.get("expected_remote_version")) is not int
                or type(observed.get("settings_version")) is not int
                or observed["settings_version"] != f["expected_remote_version"] + 1
            ):
                return "unknown"
            expected = f["patch"]
        else:
            raise ValueError("not a provisioning operation")
        return (
            "confirmed"
            if all(k in observed["config"] and observed["config"][k] == v for k, v in expected.items())
            else "unknown"
        )

    async def project(self, op):
        if op.kind == "create_space":
            department_id = op.target_manifest[0]["department_id"]
            await self._allowed(
                op.tenant_id,
                op.actor_user_id,
                "create_department" if department_id else "create_personal",
                department_id,
            )
            if await self.project_grants(op) is not True:
                return "unknown"
        elif op.kind != "update_space_settings":
            raise ValueError("not a provisioning operation")
        await self.repo.finish(op)
        return "confirmed"
