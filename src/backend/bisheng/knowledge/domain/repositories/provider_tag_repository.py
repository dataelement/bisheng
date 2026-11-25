"""Local tag identity and template import journal; never holds a lock across remote IO.

Manual tag writes share the binding's single persistent write slot with a migration
freeze, so a committed edit can never be retired by a cutover that started after it.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderBinding as Binding,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderTagRef as Ref,
)
from bisheng.knowledge.domain.models.provider_tag_import import ProviderTagImport as Plan


class TagConflict(ValueError):
    pass


@dataclass(frozen=True)
class TagScope:
    tenant_id: int
    space_id: int
    generation: int


def scoped(model, s):
    return select(model).where(
        model.tenant_id == s.tenant_id, model.space_id == s.space_id, model.generation == s.generation
    )


async def native_tag_batch(session, tenant_id, space_id, *, lock):
    statement = select(Binding).where(Binding.tenant_id == tenant_id, Binding.space_id == space_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    binding = await session.scalar(statement)
    return binding is None or (
        binding.provider_key == "native" and binding.active_generation is None and binding.state == "ready"
    )


class ProviderTagRepository:
    def __init__(self, sessions):
        self.sessions = sessions

    @asynccontextmanager
    async def transaction(self, s):
        async with self.sessions() as db, db.begin():
            binding = await db.scalar(
                select(Binding)
                .where(Binding.tenant_id == s.tenant_id, Binding.space_id == s.space_id)
                .with_for_update()
            )
            if (
                not binding
                or binding.active_generation != s.generation
                or binding.provider_key == "native"
                or binding.state != "ready"
            ):
                raise TagConflict("inactive generation")
            yield db

    async def check(self, s):
        async with self.transaction(s):
            return

    async def claim_write(self, s, token):
        """Occupy the binding's single write slot before a remote tag mutation.

        `KnowledgeProviderBinding.pending_write_operation_id` is the same column a
        migration freeze claims (provider_transfer.freeze_transfer): a committed
        freeze makes this claim refuse, and a committed claim makes that freeze
        refuse. `revision` also advances here, so a freeze that already read the
        unlocked row loses its CAS instead of retiring the edited library.

        `token` identifies one logical write; only that same write may re-enter a
        slot it retained after an unknown outcome (imports/deletes are replayable).
        Reads remain open, which is why `transaction()` itself does not demand the
        slot.
        """
        if not isinstance(token, str) or not 0 < len(token) <= 36:
            raise TagConflict("invalid write token")
        async with self.sessions() as db, db.begin():
            binding = await db.scalar(
                select(Binding)
                .where(Binding.tenant_id == s.tenant_id, Binding.space_id == s.space_id)
                .with_for_update()
            )
            if (
                not binding
                or binding.active_generation != s.generation
                or binding.provider_key == "native"
                or binding.state != "ready"
                or binding.pending_write_operation_id not in (None, token)
            ):
                raise TagConflict("inactive generation or write slot busy")
            claimed = await db.execute(
                update(Binding)
                .where(
                    Binding.tenant_id == s.tenant_id,
                    Binding.space_id == s.space_id,
                    Binding.active_generation == s.generation,
                    Binding.state == "ready",
                    Binding.revision == binding.revision,
                    or_(Binding.pending_write_operation_id.is_(None), Binding.pending_write_operation_id == token),
                )
                .values(pending_write_operation_id=token, revision=Binding.revision + 1)
            )
            if claimed.rowcount != 1:
                raise TagConflict("write slot changed")
        return token

    async def release_write(self, s, token):
        """Release only our own slot; a late release never clears another writer's claim."""
        async with self.sessions() as db, db.begin():
            released = await db.execute(
                update(Binding)
                .where(
                    Binding.tenant_id == s.tenant_id,
                    Binding.space_id == s.space_id,
                    Binding.active_generation == s.generation,
                    Binding.pending_write_operation_id == token,
                )
                .values(pending_write_operation_id=None)
            )
            return released.rowcount == 1

    async def refs(self, s, remote_ids):
        result = []
        async with self.transaction(s) as db:
            for remote in remote_ids:
                stmt = scoped(Ref, s).where(Ref.remote_tag_id == remote)
                row = await db.scalar(stmt)
                for _ in range(3):
                    if row:
                        break
                    try:
                        async with db.begin_nested():
                            row = Ref(
                                tenant_id=s.tenant_id,
                                space_id=s.space_id,
                                generation=s.generation,
                                remote_tag_id=remote,
                            )
                            db.add(row)
                            await db.flush()
                    except IntegrityError:
                        row = await db.scalar(stmt.with_for_update())
                if not row or row.state != "active":
                    raise TagConflict("tag no longer active")
                result.append(row.tag_ref_id)
        return result

    async def resolve(self, s, ids):
        async with self.transaction(s) as db:
            rows = (await db.scalars(scoped(Ref, s).where(Ref.tag_ref_id.in_(ids), Ref.state == "active"))).all()
            mapped = {r.tag_ref_id: r.remote_tag_id for r in rows}
            if any(type(i) is not int or i not in mapped for i in ids):
                raise TagConflict("unknown tag reference")
            return tuple(mapped[i] for i in ids)

    async def tombstone(self, s, ref):
        async with self.transaction(s) as db:
            row = await db.scalar(scoped(Ref, s).where(Ref.tag_ref_id == ref))
            if not row:
                raise TagConflict("unknown reference")
            row.state = "deleted"

    async def freeze(self, s, library_id, key, actor):
        from bisheng.knowledge.domain.models.knowledge_space_tag_library import KnowledgeSpaceTagLibrary as Library

        stmt = scoped(Plan, s).where(Plan.request_key == key)
        try:
            async with self.transaction(s) as db:
                row = await db.scalar(stmt)
                if row is None:
                    library = await db.scalar(
                        select(Library)
                        .where(
                            Library.id == library_id,
                            Library.tenant_id == s.tenant_id,
                            Library.owner_knowledge_id.is_(None),
                        )
                        .with_for_update()
                    )
                    if library is None:
                        raise PermissionError("public template required")
                    row = Plan(
                        tenant_id=s.tenant_id,
                        space_id=s.space_id,
                        generation=s.generation,
                        request_key=key,
                        actor_id=actor,
                        library_id=library.id,
                        words=list(library.tags),
                    )
                    db.add(row)
                    await db.flush()
                if row.actor_id != actor or row.library_id != library_id:
                    raise TagConflict("request key conflict")
                return row.id
        except IntegrityError:
            # Concurrent winner committed the same target/key. Never re-freeze its words.
            async with self.transaction(s) as db:
                row = await db.scalar(stmt)
                if not row:
                    raise
                if row.actor_id != actor or row.library_id != library_id:
                    raise TagConflict("request key conflict")
                return row.id

    async def receipt(self, s, key, actor, revision=None):
        async with self.transaction(s) as db:
            row = await db.scalar(scoped(Plan, s).where(Plan.id == key, Plan.actor_id == actor).with_for_update())
            if not row:
                raise TagConflict("unknown import")
            if revision is not None:
                if row.published_revision not in (None, revision):
                    raise TagConflict("publication receipt changed")
                row.published_revision = revision
            return tuple(row.words), row.published_revision
