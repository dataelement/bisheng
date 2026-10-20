"""Per-session workspaces for agents that run skills (F078 design decision 3).

MinIO is the source of truth: objects live under ``workspace/agent/{session}/{surface}/``
in the public bucket, so a later run of the same session can be scheduled on any
node. Every run gets a fresh local directory that is a disposable cache (C8).

One run goes through these steps (``aprepare``):

1. create a local directory unique to this run;
2. hydrate it with every workspace object except ``skills/`` — the local code
   executor only sees local files, so without this a second run could not edit
   the file the first run produced;
3. drop the previous run's ``skills/`` and copy in the configured skills, so the
   run always uses each skill's current version;
4. copy the input files into ``uploads/``;
5. snapshot the file fingerprints as the baseline for deliverable detection.

The workspace prefix is derived from the session id, so no table row is needed
to find it again; deleting a session deletes the prefix.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from loguru import logger

from bisheng.core.cache.utils import CACHE_DIR
from bisheng.linsight.domain.services.skill_provisioning import WORKSPACE_SKILLS_DIR, materialize_session_skills
from bisheng.linsight.domain.services.skill_store import SkillStore
from bisheng.linsight.domain.services.workspace_backend import WORKSPACE_PREFIX, WorkspaceBackend
from bisheng.linsight.domain.utils import snapshot_file_fingerprints

AGENT_WORKSPACE_ROOT = "agent"
UPLOADS_DIR = "uploads"

_SAFE_PART = re.compile(r"^[A-Za-z0-9_-]+$")


def _check_part(value: str, what: str) -> str:
    if not value or not _SAFE_PART.match(value):
        raise ValueError(f"unsafe workspace {what}: {value!r}")
    return value


@dataclass(frozen=True)
class WorkspaceKey:
    """Identifies one workspace: a session plus the surface that runs in it.

    ``session_key`` is a chat id (formal session) or ``tmp-<id>`` (debug session).
    ``surface`` is ``wf-<node_id>`` for a workflow agent node or ``assistant``.
    """

    session_key: str
    surface: str
    kind: str

    @classmethod
    def formal(cls, chat_id: str, surface: str) -> WorkspaceKey:
        return cls(_check_part(chat_id, "session"), _check_part(surface, "surface"), "formal")

    @classmethod
    def temp(cls, tmp_session_id: str, surface: str) -> WorkspaceKey:
        return cls(f"tmp-{_check_part(tmp_session_id, 'session')}", _check_part(surface, "surface"), "temp")

    @property
    def svid(self) -> str:
        return f"{AGENT_WORKSPACE_ROOT}/{self.session_key}/{self.surface}"

    @property
    def object_prefix(self) -> str:
        return f"{WORKSPACE_PREFIX}/{self.svid}/"


def session_object_prefix(session_key: str) -> str:
    """Object prefix that holds every workspace of one session."""
    return f"{WORKSPACE_PREFIX}/{AGENT_WORKSPACE_ROOT}/{_check_part(session_key, 'session')}/"


@dataclass
class PreparedWorkspace:
    backend: WorkspaceBackend
    file_dir: str
    baseline: dict[str, str]
    skill_names: list[str] = field(default_factory=list)


def _list_keys(minio, prefix: str) -> list[str]:
    objects = minio.minio_client_sync.list_objects(minio.bucket, prefix=prefix, recursive=True)
    return [obj.object_name for obj in objects if not getattr(obj, "is_dir", False)]


def _remove_keys(minio, keys: list[str]) -> None:
    for key in keys:
        minio.remove_object_sync(bucket_name=minio.bucket, object_name=key)


def _safe_upload_name(name: str, taken: set[str]) -> str:
    base = PurePosixPath((name or "").replace("\\", "/")).name.strip() or "file"
    stem, dot, suffix = base.rpartition(".")
    if not dot:
        stem, suffix = base, ""
    candidate, index = base, 1
    while candidate in taken:
        candidate = f"{stem}({index}).{suffix}" if suffix else f"{stem}({index})"
        index += 1
    taken.add(candidate)
    return candidate


class AgentWorkspace:
    """Prepares and cleans up the workspace of one run."""

    def __init__(
        self,
        key: WorkspaceKey,
        minio,
        tenant_id: int,
        cache_root: str | None = None,
        skill_store: SkillStore | None = None,
    ) -> None:
        self.key = key
        self.minio = minio
        self.tenant_id = tenant_id
        self.run_id = uuid.uuid4().hex
        root = cache_root or os.path.join(CACHE_DIR, "agent_runtime")
        digest = hashlib.sha1(key.svid.encode("utf-8")).hexdigest()[:16]
        # The run id keeps two concurrent runs of one workspace on one node apart.
        self.file_dir = os.path.join(root, digest, self.run_id)
        self.skill_store = skill_store

    async def aprepare(self, skills: list, input_files: list[tuple[str, bytes]]) -> PreparedWorkspace:
        """Run steps 1-5 of the module docstring and return the ready workspace.

        ``skills`` are rows already checked by ``resolve_skills``.
        ``input_files`` are ``(file name, bytes)`` pairs.
        """
        os.makedirs(self.file_dir, exist_ok=True)
        backend = WorkspaceBackend(self.key.svid, self.minio, self.file_dir)

        keys = await asyncio.to_thread(_list_keys, self.minio, self.key.object_prefix)
        skills_prefix = f"{self.key.object_prefix}{WORKSPACE_SKILLS_DIR}/"
        stale_skills = [k for k in keys if k.startswith(skills_prefix)]
        to_hydrate = [k[len(self.key.object_prefix) :] for k in keys if not k.startswith(skills_prefix)]
        await asyncio.to_thread(lambda: [backend.ensure_local(rel) for rel in to_hydrate])
        if stale_skills:
            await asyncio.to_thread(_remove_keys, self.minio, stale_skills)

        skill_names = [row.name for row in skills]
        if skill_names:
            await materialize_session_skills(
                backend,
                self.tenant_id,
                skill_names,
                store=self.skill_store,
                strict=True,
            )

        if input_files:
            taken: set[str] = set()
            pairs = [(f"/{UPLOADS_DIR}/{_safe_upload_name(name, taken)}", data) for name, data in input_files]
            await backend.aupload_files(pairs)

        baseline = await asyncio.to_thread(snapshot_file_fingerprints, self.file_dir)
        logger.info(
            "act=agent_workspace_prepare svid={} run_id={} hydrated={} skills={} inputs={}",
            self.key.svid,
            self.run_id,
            len(to_hydrate),
            skill_names,
            len(input_files),
        )
        return PreparedWorkspace(backend=backend, file_dir=self.file_dir, baseline=baseline, skill_names=skill_names)

    def cleanup_local(self) -> None:
        shutil.rmtree(self.file_dir, ignore_errors=True)


async def adelete_session_workspaces(minio, session_key: str) -> int:
    """Delete every workspace of a session; return the number of workspaces removed."""
    prefix = session_object_prefix(session_key)
    keys = await asyncio.to_thread(_list_keys, minio, prefix)
    surfaces = {key[len(prefix) :].split("/", 1)[0] for key in keys}
    await asyncio.to_thread(_remove_keys, minio, keys)
    logger.info(
        "act=agent_workspace_delete_session session={} workspaces={} objects={}", session_key, len(surfaces), len(keys)
    )
    return len(surfaces)
