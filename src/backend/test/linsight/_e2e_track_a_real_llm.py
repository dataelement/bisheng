"""Track A real-LLM end-to-end runner (AC-1) — drives the WHOLE deepagents loop.

Unlike ``_e2e_abc_runner.py`` (which substitutes the LLM), this exercises the
full Track-A path against a REAL model: ``create_linsight_agent`` -> deepagents
``astream`` -> ``StreamEventMapper.normalize`` -> ``BaseEvent`` stream, with a
real WorkspaceBackend (MinIO) so the agent's file writes land in ``output/``.

Skills / knowledge tools are intentionally NOT wired (optional, per scope); the
agent runs with deepagents' built-in todo + filesystem middleware only.

Model: configurable via ``LINSIGHT_E2E_MODEL_ID`` (default 840 = qwen3-max).

Run in a clean subprocess (no conftest premock):
    cd src/backend && config=config.yaml python test/linsight/_e2e_track_a_real_llm.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_MODEL_ID = int(os.environ.get("LINSIGHT_E2E_MODEL_ID", "840"))
_PREFIX = "e2e-f035-"
_QUESTION = "计算 2 的 10 次方等于多少。把最终答案写入工作区文件 output/answer.txt，并用一句话告诉我结果。"


async def main() -> int:
    from langgraph.checkpoint.memory import InMemorySaver

    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
    from bisheng.linsight.domain.services.agent_factory import create_linsight_agent
    from bisheng.linsight.domain.services.stream_event_mapper import StreamEventMapper
    from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend
    from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

    # Standalone script: the real worker establishes tenant context via
    # _restore_tenant_context; here we set it explicitly so model resolution
    # (TenantSystemModelConfigDao) and tenant-filtered DB reads work.
    set_current_tenant_id(1)

    svid = f"{_PREFIX}{uuid.uuid4().hex[:12]}"
    tmp = tempfile.mkdtemp()
    minio = get_minio_storage_sync()
    session_model = type(
        "S",
        (),
        {"id": svid, "tenant_id": 1, "user_id": 1, "model": None, "question": _QUESTION, "sop": None},
    )()
    backend = WorkspaceBackend(svid=svid, minio=minio, file_dir=tmp)

    print(f"[setup] svid={svid} model_id={_MODEL_ID}", flush=True)
    agent = await create_linsight_agent(
        session_model=session_model,
        tools=[],
        model_id=_MODEL_ID,
        file_dir=tmp,
        svid=svid,
        backend=backend,
        checkpointer=InMemorySaver(),
    )
    print("[ok] real deepagents agent built with model", _MODEL_ID, flush=True)

    mapper = StreamEventMapper(svid=svid)
    task_input = LinsightWorkflowTask._build_agent_input(session_model, None)
    config = {"configurable": {"thread_id": svid}, "recursion_limit": 50}

    event_counts: dict[str, int] = {}
    steps: list[str] = []
    n_chunks = 0
    try:
        async for chunk in agent.astream(
            task_input, config=config, stream_mode=["updates", "messages", "values"], subgraphs=True
        ):
            n_chunks += 1
            mode, raw, ns = LinsightWorkflowTask._unpack_stream_chunk(chunk)
            for ev in mapper.normalize(mode, raw, namespace=ns):
                et = type(ev).__name__
                event_counts[et] = event_counts.get(et, 0) + 1
                if et == "ExecStep":
                    steps.append(
                        f"{getattr(ev, 'step_type', '?')}/{getattr(ev, 'name', '?')}/{getattr(ev, 'status', '?')}"
                    )

        print(f"[stream] chunks={n_chunks}", flush=True)
        print(f"[stream] event_counts={event_counts}", flush=True)
        print(f"[stream] steps(first 25)={steps[:25]}", flush=True)

        # Verify the agent produced the deliverable through the real WorkspaceBackend.
        try:
            res = backend.read("/output/answer.txt")
            content = res.file_data["content"] if getattr(res, "file_data", None) else str(res)
            print(f"[output] output/answer.txt -> {content[:160]!r}", flush=True)
            produced = "1024" in content
        except Exception as e:
            print(f"[output] output/answer.txt NOT found: {e}", flush=True)
            produced = False

        ok = n_chunks > 0 and bool(event_counts) and produced
        print(
            f"\n=== Track A real-LLM E2E: {'PASS' if ok else 'PARTIAL'} "
            f"(chunks>0={n_chunks > 0}, events={bool(event_counts)}, deliverable_1024={produced}) ===",
            flush=True,
        )
        return 0 if ok else 2
    finally:
        # MinIO cleanup
        try:
            for obj in minio.minio_client_sync.list_objects(minio.bucket, prefix=f"workspace/{svid}/", recursive=True):
                minio.minio_client_sync.remove_object(minio.bucket, obj.object_name)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
