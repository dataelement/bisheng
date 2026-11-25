"""Short transactions for creation and settings. No remote IO under locks."""

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select, update

from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderBinding as Binding,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderGeneration as Gen,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderInstance as Instance,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderOperation as Op,
)
from bisheng.knowledge.domain.repositories.provider_operation_repository import (
    ProviderOperationRepository,
    RequestKeyConflict,
)


@dataclass(frozen=True)
class ActiveTarget:
    tenant_id: int
    space_id: int
    provider_instance_id: int
    remote_scope_id: str
    remote_kb_id: str
    generation: int
    revision: int
    pending: str | None
    capability_revision: int


class ProvisionRepository:
    def __init__(self, sessions=get_async_db_session):
        self.sessions = sessions
        self.ledger = ProviderOperationRepository()

    async def replay(self, tenant_id, kind, key, actor, identity):
        async with self.sessions() as s:
            row = await s.scalar(select(Op).where(Op.tenant_id == tenant_id, Op.kind == kind, Op.request_key == key))
            if row and (row.actor_user_id != actor or row.request_hash != identity):
                raise RequestKeyConflict("key conflict")
            if row:
                s.expunge(row)
            return row

    async def read_create_receipts(self, tenant_id, actor, item_keys):
        """Read only the caller's durable receipts; never replay or claim an operation."""
        async with self.sessions() as session:
            rows = await session.execute(
                select(Op.request_key, Op.operation_id, Op.state).where(
                    Op.tenant_id == tenant_id,
                    Op.actor_user_id == actor,
                    Op.kind == "create_space",
                    Op.request_key.in_(item_keys),
                )
            )
            return {row.request_key: row for row in rows}

    async def reserve_create(self, preset, space, actor, key, identity, config):
        tenant = preset.tenant_id
        async with self.sessions() as s:
            inst = await s.scalar(
                select(Instance)
                .where(
                    Instance.tenant_id == tenant,
                    Instance.id == preset.instance_id,
                    Instance.remote_scope_id == preset.scope,
                    Instance.provider_key == "weknora",
                )
                .with_for_update()
            )
            if not inst or inst.state != "ready" or inst.capability_revision != preset.revision:
                raise ValueError("provider preset changed")
            op = Op(
                kind="create_space",
                tenant_id=tenant,
                actor_user_id=actor,
                request_key=key,
                request_hash=identity,
                remote_kb_id=str(uuid4()),
                remote_scope_id=preset.scope,
                provider_instance_id=inst.id,
                generation=1,
                operation_epoch=1,
                phase="create",
                capability_revision=inst.capability_revision,
                target_manifest=[{"department_id": space.department_id, "name": space.name, "config": config}],
            )
            result = await self.ledger.accept(s, op)
            if result is op:
                shell = Knowledge(
                    tenant_id=tenant,
                    user_id=actor,
                    name=space.name,
                    description=space.description,
                    icon=space.icon,
                    auth_type=space.auth_type,
                    is_released=space.is_released,
                    type=KnowledgeTypeEnum.SPACE.value,
                    state=KnowledgeState.UNPUBLISHED.value,
                )
                s.add(shell)
                await s.flush()
                op.space_id = shell.id
                from bisheng.knowledge.domain.repositories.model_reference_repository import (
                    KnowledgeModelReferenceRepository,
                )

                await KnowledgeModelReferenceRepository().aadd_space_creator(s, shell, user_id=actor)
                if space.department_id is not None:
                    s.add(
                        DepartmentKnowledgeSpace(
                            tenant_id=tenant, department_id=space.department_id, space_id=shell.id, created_by=actor
                        )
                    )
                s.add(
                    Gen(
                        tenant_id=tenant,
                        space_id=shell.id,
                        provider_instance_id=inst.id,
                        remote_scope_id=preset.scope,
                        remote_kb_id=op.remote_kb_id,
                        generation=1,
                        embedding_fingerprint=sha256(
                            repr(
                                (
                                    preset.instance_id,
                                    preset.scope,
                                    preset.embedding,
                                    config["embedding_version"],
                                    config["embedding_dimension"],
                                )
                            ).encode()
                        ).hexdigest(),
                    )
                )
                s.add(
                    Binding(
                        tenant_id=tenant,
                        space_id=shell.id,
                        provider_key="weknora",
                        pending_write_operation_id=op.operation_id,
                    )
                )
            await s.flush()
            s.expunge(result)
            await s.commit()
            return result

    async def active_target(self, tenant_id, space_id):
        async with self.sessions() as s:
            row = (
                await s.execute(
                    select(Binding, Gen, Instance).where(
                        Binding.tenant_id == tenant_id,
                        Binding.space_id == space_id,
                        Binding.state == "ready",
                        Binding.provider_key == "weknora",
                        Gen.tenant_id == tenant_id,
                        Gen.space_id == space_id,
                        Gen.generation == Binding.active_generation,
                        Instance.tenant_id == tenant_id,
                        Instance.id == Gen.provider_instance_id,
                        Instance.remote_scope_id == Gen.remote_scope_id,
                        Instance.provider_key == Binding.provider_key,
                        Instance.state == "ready",
                    )
                )
            ).one_or_none()
            if not row:
                raise ValueError("no ready external binding")
            b, g, i = row
            return ActiveTarget(
                tenant_id,
                space_id,
                g.provider_instance_id,
                g.remote_scope_id,
                g.remote_kb_id,
                g.generation,
                b.revision,
                b.pending_write_operation_id,
                i.capability_revision,
            )

    async def reserve_settings(self, t, actor, key, identity, patch, expected_remote_version):
        async with self.sessions() as s:
            verified = await s.scalar(
                select(Instance.id)
                .where(
                    Instance.id == t.provider_instance_id,
                    Instance.tenant_id == t.tenant_id,
                    Instance.remote_scope_id == t.remote_scope_id,
                    Instance.provider_key == "weknora",
                    Instance.state == "ready",
                    Instance.capability_revision == t.capability_revision,
                )
                .with_for_update()
            )
            if verified is None:
                raise ValueError("provider preset changed")
            op = Op(
                kind="update_space_settings",
                tenant_id=t.tenant_id,
                space_id=t.space_id,
                actor_user_id=actor,
                request_key=key,
                request_hash=identity,
                remote_kb_id=t.remote_kb_id,
                remote_scope_id=t.remote_scope_id,
                provider_instance_id=t.provider_instance_id,
                generation=t.generation,
                operation_epoch=1,
                expected_revision=t.revision,
                phase="settings",
                capability_revision=t.capability_revision,
                target_manifest=[{"patch": patch, "expected_remote_version": expected_remote_version}],
            )
            result = await self.ledger.accept(s, op)
            if result is op:
                changed = await s.execute(
                    update(Binding)
                    .where(
                        Binding.tenant_id == t.tenant_id,
                        Binding.space_id == t.space_id,
                        Binding.active_generation == t.generation,
                        Binding.state == "ready",
                        Binding.revision == t.revision,
                        Binding.pending_write_operation_id.is_(None),
                    )
                    .values(pending_write_operation_id=op.operation_id)
                )
                if changed.rowcount != 1:
                    raise ValueError("settings revision or pending write conflict")
            s.expunge(result)
            await s.commit()
            return result

    async def require_send_target(self, op):
        """A claim alone doesn't prove the frozen target is still writable."""
        async with self.sessions() as s:
            stmt = select(Binding.id).where(
                Binding.tenant_id == op.tenant_id,
                Binding.space_id == op.space_id,
                Binding.provider_key == "weknora",
                Binding.pending_write_operation_id == op.operation_id,
                Gen.tenant_id == Binding.tenant_id,
                Gen.space_id == Binding.space_id,
                Gen.generation == op.generation,
                Gen.provider_instance_id == op.provider_instance_id,
                Gen.remote_kb_id == op.remote_kb_id,
                Gen.remote_scope_id == op.remote_scope_id,
                Instance.id == Gen.provider_instance_id,
                Instance.tenant_id == Gen.tenant_id,
                Instance.remote_scope_id == Gen.remote_scope_id,
                Instance.capability_revision == op.capability_revision,
                Instance.state == "ready",
                Instance.provider_key == Binding.provider_key,
                Op.tenant_id == Binding.tenant_id,
                Op.operation_id == Binding.pending_write_operation_id,
                Op.state == "sending",
                Op.lease_token == op.lease_token,
                Op.revision == op.revision,
                Op.lease_until > datetime.now(UTC).replace(tzinfo=None),
            )
            if op.kind == "update_space_settings":
                stmt = stmt.where(
                    Binding.state == "ready",
                    Binding.active_generation == op.generation,
                    Binding.revision == op.expected_revision,
                )
            elif op.kind == "create_space":
                stmt = stmt.where(Binding.state == "provisioning", Binding.active_generation.is_(None))
            else:
                raise ValueError("not a provisioning operation")
            if await s.scalar(stmt) is None:
                raise ValueError("stale provisioning target")

    async def finish(self, op):
        async with self.sessions() as s:
            live = await s.scalar(
                select(Op)
                .where(
                    Op.tenant_id == op.tenant_id,
                    Op.operation_id == op.operation_id,
                    Op.space_id == op.space_id,
                    Op.generation == op.generation,
                    Op.operation_epoch == op.operation_epoch,
                    Op.state == "applying",
                    Op.lease_token == op.lease_token,
                    Op.lease_until > datetime.now(UTC).replace(tzinfo=None),
                    Op.revision == op.revision,
                )
                .with_for_update()
            )
            if not live:
                raise ValueError("lost projection lease")
            b = await s.scalar(
                select(Binding)
                .where(
                    Binding.tenant_id == op.tenant_id,
                    Binding.space_id == op.space_id,
                    Binding.provider_key == "weknora",
                )
                .with_for_update()
            )
            if not b:
                raise ValueError("missing binding")
            if b.pending_write_operation_id != op.operation_id:
                # A crash between the local commit and worker ACK permits another
                # claim. The completion marker is on this exact operation.
                if live.phase == "projected":
                    return
                raise ValueError("binding reservation changed")
            if op.kind == "create_space" and b.active_generation is None:
                g = await s.scalar(
                    select(Gen).where(
                        Gen.tenant_id == op.tenant_id,
                        Gen.space_id == op.space_id,
                        Gen.generation == op.generation,
                        Gen.remote_kb_id == op.remote_kb_id,
                        Gen.provider_instance_id == op.provider_instance_id,
                        Gen.remote_scope_id == op.remote_scope_id,
                    )
                )
                if not g:
                    raise ValueError("frozen target changed")
                g.state = b.state = "ready"
                b.active_generation = op.generation
                changed = await s.execute(
                    update(Knowledge)
                    .where(
                        Knowledge.tenant_id == op.tenant_id,
                        Knowledge.id == op.space_id,
                        Knowledge.state == KnowledgeState.UNPUBLISHED.value,
                    )
                    .values(state=KnowledgeState.PUBLISHED.value)
                )
                if changed.rowcount != 1:
                    raise ValueError("space reservation changed")
            elif (
                op.kind != "update_space_settings"
                or b.active_generation != op.generation
                or b.revision != op.expected_revision
            ):
                raise ValueError("binding revision changed")
            b.revision += 1
            b.pending_write_operation_id = None
            live.phase = "projected"
            await s.commit()
