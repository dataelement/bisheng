"""Real-middleware E2E runner for F035 Tracks A/B/C (F035 task mode).

Run in a CLEAN subprocess (no pytest conftest premock) so it talks to the REAL
infrastructure configured in ``bisheng/config.yaml`` — real Redis (Track B
checkpointer), real MinIO (Track C WorkspaceBackend), real deepagents (Track A
agent assembly). The pytest wrapper ``test_e2e_abc.py`` invokes this and asserts
on the JSON it prints, so the conftest's MagicMock'd ``redis_manager`` never
intercepts these checks.

Output: a single JSON object on the last stdout line:
    {"checks": [{"name": ..., "ok": bool, "detail": ...}, ...]}

Usage (driven by the pytest wrapper):
    cd src/backend && config=config.yaml python test/linsight/_e2e_abc_runner.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import traceback
import uuid

# Ensure the backend package root is importable when run as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_PREFIX = "e2e-f035-"
_CHECKS: list[dict] = []


def _svid() -> str:
    return f"{_PREFIX}{uuid.uuid4().hex[:12]}"


def record(name: str, ok: bool, detail: str = "") -> None:
    _CHECKS.append({"name": name, "ok": bool(ok), "detail": str(detail)[:160]})


# ---------------------------------------------------------------------------
# Track B (AC-5) — PlainRedisCheckpointer against REAL Redis
# ---------------------------------------------------------------------------
async def track_b() -> None:
    from langgraph.checkpoint.base import empty_checkpoint

    from bisheng.linsight.domain.services.checkpointer import make_checkpointer

    saver = make_checkpointer(ttl_seconds=120)
    thread_id = _svid()
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    cp = empty_checkpoint()
    # The test thread's keys expire via the 120s TTL set on the saver above; the
    # old adelete_thread purge (and its AC-5 assertion) was removed together with
    # that dead checkpointer method.
    next_config = await saver.aput(config, cp, {"source": "e2e", "step": 1}, {})
    tup = await saver.aget_tuple(next_config)
    record(
        "B/AC-5 checkpoint round-trip (real Redis)",
        tup is not None and tup.checkpoint["id"] == cp["id"] and tup.metadata.get("source") == "e2e",
        f"id={tup.checkpoint['id'][:8] if tup else None}",
    )

    listed = [t async for t in saver.alist(config)]
    record("B/AC-5 alist chronological index", any(t.checkpoint["id"] == cp["id"] for t in listed))

    await saver.aput_writes(next_config, [("messages", {"resume": "the answer"})], task_id="task-e2e")
    tup2 = await saver.aget_tuple(next_config)
    record("B/AC-5 pending_writes round-trip (resume payload)", bool(tup2 and tup2.pending_writes))


# ---------------------------------------------------------------------------
# Track C (AC-6) — WorkspaceBackend against REAL MinIO
# ---------------------------------------------------------------------------
def track_c() -> None:
    from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
    from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend

    minio = get_minio_storage_sync()

    def purge(svid: str) -> None:
        try:
            for obj in minio.minio_client_sync.list_objects(minio.bucket, prefix=f"workspace/{svid}/", recursive=True):
                minio.minio_client_sync.remove_object(minio.bucket, obj.object_name)
        except Exception:
            pass

    def ls_paths(be, p: str = "/") -> str:
        res = be.ls(p)
        entries = getattr(res, "entries", None) or []
        return " ".join(str(getattr(e, "path", getattr(e, "name", e))) for e in entries)

    # write-through + read + ls
    svid = _svid()
    be = WorkspaceBackend(svid=svid, minio=minio, file_dir=tempfile.mkdtemp())
    try:
        be.write("/output/report.md", "# E2E Report\nline2\n")
        be.write("/scratch/tmp.txt", "intermediate")
        res = be.read("/output/report.md")
        content = res.file_data["content"] if getattr(res, "file_data", None) else str(res)
        record("C/AC-6 write-through + read (real MinIO)", "E2E Report" in content)
        listed = ls_paths(be)
        record(
            "C/AC-6 ls authoritative from MinIO",
            "output/report.md" in listed and "scratch/tmp.txt" in listed,
            listed[:100],
        )
    finally:
        purge(svid)

    # lazy load: MinIO is truth, fresh cache re-materializes
    svid2 = _svid()
    be2 = WorkspaceBackend(svid=svid2, minio=minio, file_dir=tempfile.mkdtemp())
    try:
        be2.write("/output/data.txt", "durable-content")
        be3 = WorkspaceBackend(svid=svid2, minio=minio, file_dir=tempfile.mkdtemp())  # empty cache
        res = be3.read("/output/data.txt")
        content = res.file_data["content"] if getattr(res, "file_data", None) else str(res)
        record("C/AC-6 lazy-load from MinIO after cache clear", "durable-content" in content)
    finally:
        purge(svid2)

    # tenant isolation between svids
    a, b = _svid(), _svid()
    be_a = WorkspaceBackend(svid=a, minio=minio, file_dir=tempfile.mkdtemp())
    be_b = WorkspaceBackend(svid=b, minio=minio, file_dir=tempfile.mkdtemp())
    try:
        be_a.write("/output/secret.txt", "tenant-A-only")
        record("C/AC-6+AC-7 tenant isolation between svids", "secret.txt" not in ls_paths(be_b))
    finally:
        purge(a)
        purge(b)


# ---------------------------------------------------------------------------
# Track A (AC-1) — create_linsight_agent assembles a REAL deepagents graph
# ---------------------------------------------------------------------------
async def track_a() -> None:
    from unittest.mock import patch

    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langgraph.checkpoint.memory import InMemorySaver

    from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
    from bisheng.linsight.domain.services.agent_factory import create_linsight_agent
    from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend

    svid = _svid()
    session_model = type("S", (), {"id": svid, "tenant_id": 1, "user_id": 1, "model": None})()
    tmp = tempfile.mkdtemp()
    # Real WorkspaceBackend; LLM is an external service -> substituted by a fake.
    backend = WorkspaceBackend(svid=svid, minio=get_minio_storage_sync(), file_dir=tmp)
    with patch(
        "bisheng.linsight.domain.services.agent_factory._resolve_model",
        return_value=GenericFakeChatModel(messages=iter([])),
    ):
        agent = await create_linsight_agent(
            session_model=session_model,
            tools=[],
            model_id=None,
            file_dir=tmp,
            svid=svid,
            backend=backend,
            checkpointer=InMemorySaver(),
        )
    record(
        "A/AC-1 create_linsight_agent builds real deepagents graph",
        agent is not None and hasattr(agent, "astream"),
    )


async def main() -> int:
    for name, coro in (("track_a", track_a),):
        try:
            await coro()
        except Exception as e:
            record(name, False, f"{type(e).__name__}: {e}")
            traceback.print_exc(file=sys.stderr)
    try:
        track_c()
    except Exception as e:
        record("track_c", False, f"{type(e).__name__}: {e}")
        traceback.print_exc(file=sys.stderr)
    try:
        await track_b()
    except Exception as e:
        record("track_b", False, f"{type(e).__name__}: {e}")
        traceback.print_exc(file=sys.stderr)

    print(json.dumps({"checks": _CHECKS}))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
