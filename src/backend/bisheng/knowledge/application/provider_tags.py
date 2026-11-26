"""Application boundary for generation-bound vocabulary and manual tag relations.

Callers supply a trusted scope, a target-bound capability-checked port, and the
current actor's authorization callback. Remote IDs never enter client DTOs.

Every remote mutation first occupies the binding's single write slot, which a
migration freeze claims too: an edit that committed can therefore never be
followed by a cutover that retires the library holding it.
"""

from contextlib import asynccontextmanager
from hashlib import sha256
from uuid import uuid4

from bisheng.knowledge.domain.repositories.provider_tag_repository import TagConflict, TagScope

__all__ = ["ProviderTags", "TagConflict", "TagContractUnavailable", "TagScope", "TagWriteRejected"]


class TagWriteRejected(Exception):
    """A definitive refusal at the dedicated write route; nothing was committed."""


class TagContractUnavailable(Exception):
    """The bound upstream has no per-document manual tag contract.

    Raised only when the dedicated route is absent, so the caller can decide
    whether a documented whole-set fallback is permitted for this deployment.
    """


class ProviderTags:
    def __init__(self, repository, port, *, authorize):
        self.repo, self.port, self.authorize = repository, port, authorize

    @staticmethod
    def _write_token(kind, identity=None):
        """Deterministic for replayable writes, unique per attempt for manual edits.

        A deterministic token lets the same logical write resume the slot it left
        occupied after an unknown outcome. A manual edit gets a fresh token so a
        timed-out edit can never resend itself; the slot stays until reconciled.
        """
        digest = uuid4().hex if identity is None else sha256(f"{kind}:{identity}".encode()).hexdigest()[:32]
        return "tag:" + digest

    @asynccontextmanager
    async def _write_slot(self, scope, token, *, before_send=None):
        """Hold the shared write slot across the remote mutation, never across SQL locks.

        A refused remote precondition (`TagConflict`) proves nothing was applied, so
        the slot is released for the next attempt. Any other failure may have applied
        remotely and keeps the slot: neither a freeze nor another write may pass an
        unknown tag mutation until it is reconciled.
        """
        await self.repo.claim_write(scope, token)
        if before_send is not None:
            try:
                await before_send()
            except BaseException:
                # The caller has not entered the remote mutation yet, even on cancellation.
                await self.repo.release_write(scope, token)
                raise
        try:
            yield token
        except (TagConflict, TagWriteRejected):
            await self.repo.release_write(scope, token)
            raise
        else:
            await self.repo.release_write(scope, token)

    async def _require(self, scope, action, file_id=None):
        if not await self.authorize(scope, action, file_id):
            raise PermissionError("tag action denied")
        await self.repo.check(scope)

    async def page(self, scope, *, page, page_size):
        await self._require(scope, "view")
        if page < 1 or not 1 <= page_size <= 200:
            raise ValueError("invalid pagination")
        rows, total = await self.port.page(scope, page, page_size)
        refs = await self.repo.refs(scope, [remote for remote, _ in rows])
        return {
            "data": [{"tag_ref_id": ref, "name": name} for ref, (_, name) in zip(refs, rows, strict=True)],
            "total": total,
        }

    async def resolve(self, scope, refs):
        await self._require(scope, "view")
        return await self.repo.resolve(scope, refs)

    async def create_word(self, scope, name):
        await self._require(scope, "edit_space")
        if not name.strip():
            raise ValueError("empty tag name")
        async with self._write_slot(scope, self._write_token("word", name.strip())):
            remote = await self.port.create_word(scope, name.strip())
            return (await self.repo.refs(scope, [remote]))[0]

    async def delete(self, scope, ref):
        await self._require(scope, "edit_space")
        (remote,) = await self.repo.resolve(scope, [ref])
        async with self._write_slot(scope, self._write_token("delete", ref)):
            await self.port.delete_relations_only(scope, remote)
            await self.repo.tombstone(scope, ref)

    async def edit(self, scope, file_id, mode, refs, *, expected_revision=None, before_send=None):
        await self._require(scope, "edit_file", file_id)
        if mode not in ("append", "replace", "clear"):
            raise ValueError("unknown edit mode")
        if mode != "append" and (type(expected_revision) is not int or expected_revision < 0):
            raise TagConflict("expected revision required")
        if (mode == "clear" and refs) or (mode == "replace" and not refs):
            raise TagConflict("use explicit clear")
        if mode == "append" and not refs:
            return
        remote = await self.repo.resolve(scope, refs)
        async with self._write_slot(scope, self._write_token("edit"), before_send=before_send):
            return await self.port.edit_manual(scope, file_id, mode, remote, expected_revision)

    async def edit_whole(self, scope, file_id, mode, refs, *, write, before_send=None):
        """Whole-set fallback for an upstream without the per-document contract.

        The remote keeps one tag list per document and ignores revisions, so the
        port re-reads and compares the browser revision immediately before it
        writes. `write` performs that read/write/confirm and returns the new raw
        revision; the shared write slot is still held for the whole mutation.
        """
        await self._require(scope, "edit_file", file_id)
        if mode not in ("replace", "clear") or (mode == "clear") != (not refs):
            raise TagConflict("use explicit clear")
        remote = await self.repo.resolve(scope, refs) if refs else ()
        async with self._write_slot(scope, self._write_token("edit"), before_send=before_send):
            return await write(remote)

    async def precheck_append(self, scope, file_ids, refs, *, new_names=()):
        """Inspection only. Never create vocabulary, mutate relations or claim a receipt."""
        await self.resolve(scope, refs)
        if new_names:
            await self._require(scope, "edit_space")
        allowed = []
        denied = []
        for file_id in dict.fromkeys(file_ids):
            permitted = await self.authorize(scope, "edit_file", file_id)
            (allowed if permitted else denied).append(file_id)
        await self.repo.check(scope)
        return tuple(allowed), tuple(denied)

    async def classify(self, scope, version_id):
        await self._require(scope, "classify", version_id)
        revision = await self.port.published_revision(scope)
        if revision is None:
            return None
        return await self.port.classify_version(scope, version_id, revision)

    async def freeze_template(self, scope, library_id, *, request_key, actor_id):
        await self._require(scope, "edit_space")
        return await self.repo.freeze(scope, library_id, request_key, actor_id)

    async def resume_import(self, scope, key, *, actor_id):
        await self._require(scope, "edit_space")
        words, revision = await self.repo.receipt(scope, key, actor_id)
        if revision is not None:
            return revision
        async with self._write_slot(scope, self._write_token("import", key)):
            # Re-read under the slot: a resumed attempt must reuse the published
            # revision instead of importing a second time.
            words, revision = await self.repo.receipt(scope, key, actor_id)
            if revision is not None:
                return revision
            revision = await self.port.import_receipt(scope, key)
            if revision is None:
                revision = await self.port.import_if_absent(scope, key, words)
            if type(revision) is not int or revision <= 0:
                raise TagConflict("invalid publication receipt")
            await self.repo.receipt(scope, key, actor_id, revision)
            return revision
