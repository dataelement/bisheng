"""Control-plane transfer after business admission, never a content or HTTP proxy.

The executor re-ingests only the frozen source files into the operation's exact
library. It supplies *verified upstream readback*, not task acceptance, to apply.
No network call runs inside these caller-owned SQL transactions.

Cutover is one atomic pointer + watermark install: the target library's own
verified Wiki revision replaces the retired library's, which upstream counts
per library. Tag writes and this freeze share the binding's single write slot,
so a committed edit and a cutover can never both succeed.
"""

import json
from dataclasses import dataclass
from hashlib import sha256

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderOperation as Operation
from bisheng.knowledge.domain.repositories import provider_transfer_repository as repo
from bisheng.knowledge.domain.repositories.provider_operation_repository import ProviderOperationRepository
from bisheng.knowledge.domain.repositories.provider_wiki_repository import (
    WikiObservation,
    verified_target_watermark,
)


def _reject(reason):
    raise KnowledgeOperationPlanConflictError(reason="provider_transfer_" + reason)


@dataclass(frozen=True, slots=True)
class FileProof:
    file_id: int
    version_id: int
    remote_object_id: str
    byte_count: int
    checksum: str


@dataclass(frozen=True, slots=True)
class TransferProof:
    operation_id: str
    tenant_id: int
    space_id: int
    generation: int
    instance_id: int
    scope_id: str
    kb_id: str
    embedding_fingerprint: str
    content_revision: int
    # Read-only proof of the target library's converged Wiki watermark.
    wiki: WikiObservation
    files: tuple[FileProof, ...]


@dataclass(frozen=True, slots=True)
class LibraryTarget:
    generation: int
    instance_id: int
    scope_id: str
    kb_id: str
    embedding_fingerprint: str
    content_revision: int


@dataclass(frozen=True, slots=True)
class ReingestPlan:
    tenant_id: int
    space_id: int
    operation_id: str
    epoch: int
    source: LibraryTarget
    target: LibraryTarget
    files: tuple[FileProof, ...]


async def execute_frozen_transfer(op, *, port, now):
    """Call only after committing the claim. Adapter must deduplicate on operation_id/epoch.

    The port must validate server receipts and current authorization before sending.
    Takeover polls the original library; unresolved outcomes never cause a resend.
    """
    if (
        op.kind != "provider_transfer"
        or not op.lease_token
        or not op.lease_until
        or op.lease_until <= now
        or op.state not in ("sending", "waiting_remote", "reconciling", "applying")
    ):
        _reject("claim_required")
    header, *files = op.target_manifest
    source, target = LibraryTarget(**header["source"]), LibraryTarget(**header["target"])
    if (target.instance_id, target.scope_id, target.kb_id, target.generation) != (
        op.provider_instance_id,
        op.remote_scope_id,
        op.remote_kb_id,
        op.generation,
    ):
        _reject("target_changed")
    plan = ReingestPlan(
        op.tenant_id,
        op.space_id,
        op.operation_id,
        op.operation_epoch,
        source,
        target,
        tuple(FileProof(f["file_id"], f["version_id"], f["source_id"], f["byte_count"], f["checksum"]) for f in files),
    )
    return await (port.reingest(plan) if op.state == "sending" else port.readback(plan))


async def require_native_mutation(session, *, tenant_id, space_id, operation):
    """Legacy mutations have no remote equivalent yet; absent binding is legacy native."""
    b = await repo.binding(session, tenant_id, space_id)
    if b and (
        b.provider_key != "native"
        or b.active_generation is not None
        or b.state != "ready"
        or b.pending_write_operation_id
    ):
        _reject("unsupported_" + operation)


async def quarantine_generation(session, *, tenant_id, space_id, generation, expected_revision):
    """Fail closed after DR discrepancy; stale observations cannot disable a newer generation."""
    return await repo.change_binding(session, tenant_id, space_id, generation, expected_revision, state="quarantined")


def _identity(g):
    return {
        "generation": g.generation,
        "instance_id": g.provider_instance_id,
        "scope_id": g.remote_scope_id,
        "kb_id": g.remote_kb_id,
        "embedding_fingerprint": g.embedding_fingerprint,
        "content_revision": g.content_revision,
    }


async def _source_files(session, source):
    amounts = {}
    subjects = {}
    for q in await repo.charges(session, source):
        fact = (q.byte_count, q.receipt_checksum, q.operation_id)
        pair = subjects.setdefault(q.version_id, set())
        if (
            q.accounting_kind != "original_bytes"
            or q.state != "charged"
            or not q.receipt_checksum
            or q.subject_type not in ("user", "tenant")
            or q.subject_type in pair
            or (q.subject_type == "tenant" and q.subject_id != source.tenant_id)
            or amounts.setdefault(q.version_id, fact) != fact
        ):
            _reject("source_charge_unproved")
        pair.add(q.subject_type)
    if any(pair != {"user", "tenant"} for pair in subjects.values()):
        _reject("source_charge_incomplete")
    files = []
    for m in await repo.mappings(session, source):
        # Directory/tag projection copying is not proved. Do not silently drop it.
        if (
            m.resource_type != "file"
            or m.tombstoned_at
            or m.lifecycle_state != "active"
            or m.ready_revision is None
            or not m.version_id
            or m.version_id not in amounts
        ):
            _reject("source_not_ready")
        size, checksum, _ = amounts.pop(m.version_id)
        files.append(
            {
                "file_id": m.local_resource_id,
                "version_id": m.version_id,
                "document_id": m.logical_document_id,
                "source_id": m.remote_object_id,
                "epoch": m.operation_epoch,
                "ready_revision": m.ready_revision,
                "revision": m.revision,
                "byte_count": size,
                "checksum": checksum,
            }
        )
    if amounts:
        _reject("source_mapping_missing")
    return files


async def freeze_transfer(
    session, *, tenant_id, space_id, actor_user_id, request_key, target_generation, expected_revision
):
    """Freeze the old and new targets; reserve the binding's write slot, not bytes.

    The slot is the same one manual tag writes claim (provider_tags.ProviderTags):
    a tag write in flight, or one whose outcome is unknown and therefore still
    holds the slot, makes this freeze refuse; a committed freeze makes every later
    tag write refuse until cutover. The revision CAS additionally defeats a freeze
    that read the row before a concurrent edit advanced it.
    """
    digest = sha256(json.dumps([tenant_id, space_id, target_generation, expected_revision]).encode()).hexdigest()
    b = await repo.binding(session, tenant_id, space_id)
    replay = await repo.replay(session, tenant_id, request_key)
    if replay:
        if replay.actor_user_id != actor_user_id or replay.request_hash != digest:
            _reject("request_key_conflict")
        return replay
    if (
        not b
        or b.state != "ready"
        or b.provider_key == "native"
        or not b.active_generation
        or b.active_generation >= target_generation
        or b.revision != expected_revision
        or b.pending_write_operation_id  # another write, including a tag edit, owns the slot
        or b.wiki_target_revision != b.wiki_applied_revision
    ):
        _reject("binding_changed")
    old = await repo.generation(session, tenant_id, space_id, b.active_generation)
    new = await repo.generation(session, tenant_id, space_id, target_generation)
    if (
        not old
        or not new
        or old.state != "ready"
        or new.state != "provisioning"
        or not new.embedding_fingerprint
        or not old.embedding_fingerprint
        or (old.provider_instance_id, old.remote_scope_id, old.remote_kb_id)
        == (new.provider_instance_id, new.remote_scope_id, new.remote_kb_id)
        or await repo.mappings(session, new)
    ):
        _reject("generation_unavailable")
    i = await repo.instance(session, tenant_id, new.provider_instance_id)
    if (
        not i
        or i.state != "ready"
        or i.provider_key != b.provider_key
        or i.remote_scope_id != new.remote_scope_id
        or not i.capability_revision
    ):
        _reject("instance_unverified")
    manifest = [{"source": _identity(old), "target": _identity(new)}, *await _source_files(session, old)]
    op = await ProviderOperationRepository().accept(
        session,
        Operation(
            tenant_id=tenant_id,
            space_id=space_id,
            actor_user_id=actor_user_id,
            kind="provider_transfer",
            request_key=request_key,
            request_hash=digest,
            generation=new.generation,
            provider_instance_id=new.provider_instance_id,
            remote_scope_id=new.remote_scope_id,
            remote_kb_id=new.remote_kb_id,
            operation_epoch=expected_revision + 1,
            expected_revision=expected_revision + 1,
            capability_revision=i.capability_revision,
            target_manifest=manifest,
            phase="reingest",
        ),
    )
    if not await repo.change_binding(
        session, tenant_id, space_id, old.generation, expected_revision, pending_write_operation_id=op.operation_id
    ):
        _reject("freeze_conflict")
    return op


async def apply_transfer(
    session, *, tenant_id, operation_id, lease_token, expected_revision, now, proof: TransferProof
):
    op = await repo.operation(session, tenant_id, operation_id)
    if (
        not op
        or op.kind != "provider_transfer"
        or not lease_token
        or op.lease_token != lease_token
        or op.revision != expected_revision
        or not op.lease_until
        or op.lease_until <= now
        or op.state not in ("sending", "reconciling", "waiting_remote", "applying")
    ):
        return False
    header, *files = op.target_manifest
    b = await repo.binding(session, tenant_id, op.space_id)
    if (
        not b
        or b.state != "ready"
        or b.pending_write_operation_id != op.operation_id
        or b.revision != op.expected_revision
        or b.active_generation != header["source"]["generation"]
        or b.wiki_target_revision != b.wiki_applied_revision
    ):
        return False
    old = await repo.generation(session, tenant_id, op.space_id, b.active_generation)
    new = await repo.generation(session, tenant_id, op.space_id, op.generation)
    if (
        not old
        or not new
        or old.state != "ready"
        or new.state != "provisioning"
        or (op.provider_instance_id, op.remote_scope_id, op.remote_kb_id)
        != (new.provider_instance_id, new.remote_scope_id, new.remote_kb_id)
        or header["source"] != _identity(old)
        or header["target"] | {"content_revision": new.content_revision} != _identity(new)
        or new.content_revision < header["target"]["content_revision"]
    ):
        return False
    i = await repo.instance(session, tenant_id, new.provider_instance_id)
    if (
        not i
        or i.state != "ready"
        or i.capability_revision != op.capability_revision
        or i.provider_key != b.provider_key
        or i.remote_scope_id != new.remote_scope_id
    ):
        return False
    if (proof.operation_id, proof.tenant_id, proof.space_id) != (op.operation_id, tenant_id, op.space_id) or any(
        getattr(proof, k) != v for k, v in _identity(new).items()
    ):
        return False
    # A cutover retires the library whose watermark is still installed here.
    # Without a verified read of the *target* library, the barrier stays and the
    # old numbers are neither reused nor reset to zero.
    watermark = verified_target_watermark(b, new, proof.wiki)
    if watermark is None:
        return False
    if files != await _source_files(session, old):
        return False
    rows = await repo.mappings(session, new)
    target_by_file = {m.local_resource_id: m for m in rows}
    if len(files) != len(rows) or len(files) != len(proof.files):
        return False
    expected = set()
    for f in files:
        m = target_by_file.get(f["file_id"])
        if (
            not m
            or m.resource_type != "file"
            or m.version_id != f["version_id"]
            or m.logical_document_id != f["document_id"]
            or m.tombstoned_at
            or m.lifecycle_state != "active"
            or m.ready_revision is None
            or m.ready_revision > new.content_revision
        ):
            return False
        expected.add(FileProof(m.local_resource_id, m.version_id, m.remote_object_id, f["byte_count"], f["checksum"]))
    if expected != set(proof.files):
        return False
    if not await repo.change_binding(
        session,
        tenant_id,
        b.space_id,
        old.generation,
        b.revision,
        active_generation=new.generation,
        pending_write_operation_id=None,
        wiki_target_revision=watermark,
        wiki_applied_revision=watermark,
    ):
        return False
    old.state = "retired"
    old.revision += 1
    new.state = "ready"
    new.revision += 1
    op.state = "succeeded"
    op.phase = "cutover"
    op.revision += 1
    op.lease_token = None
    op.lease_until = None
    op.next_attempt_at = None
    await session.flush()
    return True
