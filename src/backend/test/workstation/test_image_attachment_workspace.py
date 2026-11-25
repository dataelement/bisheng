"""F004 design §7 item 18: the images a visual model gets directly also go into ``uploads/``.

Before: an image attachment of a visual model was only an ``image_url`` block of
the model input, so a later run could not ``read_file`` it or open it in the
code interpreter. Now the original is written to
``workspace/{conversation_id}/uploads/<name>`` in the background; the first model
request does not wait for the write and its input names the path.

The REAL graph runs with a scripted model. Redis is fakeredis, the object store
is a dict. The runner-level tests use a fake attachment source; the production
source is tested against the dict store.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from loguru import logger

from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend
from bisheng.workstation.domain.services import direct_attachments, direct_run
from bisheng.workstation.domain.services.direct_run import DirectRunContext
from test.workstation.test_attachment_on_demand import _async, _Store
from test.workstation.test_direct_run import CID, TENANT, USER, _Env

PNG = {"filepath": "tmp/chart.png?sig=1", "file_name": "chart.png", "file_id": "a" * 32}
PNG_AGAIN = {"filepath": "tmp/other/chart.png?sig=1", "file_name": "chart.png", "file_id": "b" * 32}
PDF = {"filepath": "tmp/b.pdf?sig=1", "file_name": "b.pdf", "file_id": "e" * 32}
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR-not-a-real-picture"
DATA_URL = "data:image/png;base64,AAAA"
LIMITS = {"inline_chars": 4000, "inline_total_chars": 15000}


@pytest.fixture
def make_env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    def _make(script: list[Any], *, visual: bool = True) -> _Env:
        env = _Env(monkeypatch, tmp_path, script)
        # The model is declared vision-capable, so the content guard keeps image blocks.
        monkeypatch.setattr(agent_factory, "_resolve_model", AsyncMock(return_value=(env.model, visual)))
        return env

    return _make


def _frames(events: list[dict]) -> list[dict]:
    return [e for e in events if e["type"] == "tool_call" and e["data"]["name"] == direct_run.ATTACHMENT_TOOL_NAME]


def _first_user_content(env: _Env) -> list[dict]:
    content = next(m for m in env.model.inputs[0] if m.type == "human").content
    assert isinstance(content, list), "a visual model gets the image as a content block"
    return content


class _VisualSource:
    """A model that takes images. ``store_image`` blocks until ``release()``."""

    inline_chars = 4000
    inline_total_chars = 15000

    def __init__(self, env: _Env, *, store_error: BaseException | None = None):
        self.env = env
        self.gate = asyncio.Event()
        self.store_started: list[str] = []
        self.stored: list[str] = []
        self.ingested: list[str] = []
        self.store_error = store_error

    def release(self) -> None:
        self.gate.set()

    async def ready(self, ctx: DirectRunContext, file: dict) -> bool:
        return False

    async def visual(self, ctx: DirectRunContext) -> bool:
        return True

    async def image_data_url(self, ctx: DirectRunContext, file: dict) -> str:
        return DATA_URL

    async def store_image(self, ctx: DirectRunContext, file: dict, used_names: set[str]) -> dict:
        self.store_started.append(file["file_name"])
        await self.gate.wait()
        if self.store_error is not None:
            raise self.store_error
        # The name the production source would pick: the original name, de-duplicated.
        name, n = file["file_name"], 2
        while name in used_names:
            stem, ext = file["file_name"].rsplit(".", 1)
            name, n = f"{stem}-{n}.{ext}", n + 1
        self.env.store.objects[f"workspace/{ctx.conversation_id}/uploads/{name}"] = PNG_BYTES
        self.stored.append(name)
        return {
            "file_id": file["file_id"],
            "original_filename": file["file_name"],
            "parsing_status": "completed",
            "valid": True,
            "workspace_path": f"/uploads/{name}",
        }

    async def ingest(self, ctx: DirectRunContext, file: dict, used_names: set[str]) -> dict:
        self.ingested.append(file["file_name"])
        stem = file["file_name"].rsplit(".", 1)[0]
        self.env.store.objects[f"workspace/{ctx.conversation_id}/uploads/{stem}.md"] = b"text"
        return {
            "file_id": file["file_id"],
            "original_filename": file["file_name"],
            "parsing_status": "completed",
            "valid": True,
            "workspace_path": f"/uploads/{stem}.md",
            "line_count": 1,
        }

    async def text(self, ctx: DirectRunContext, entry: dict) -> str | None:
        return "text"


async def _submit(env: _Env, text: str, files: list[dict]) -> DirectRunContext:
    ctx = await env.submit(text)
    ctx.files = [dict(f) for f in files]
    return ctx


async def _drain_background() -> None:
    await asyncio.gather(*list(direct_attachments._BACKGROUND))
    # The done callbacks that empty the set run on the next loop turn.
    await asyncio.sleep(0)


# --------------------------------------------------------------------- runner


async def test_image_is_written_to_uploads_without_delaying_the_model_request(make_env):
    seen: dict[str, Any] = {}

    async def answer(messages: list) -> AIMessage:
        # The model is asked while the write to the workspace has not finished.
        seen["store_started"] = list(source.store_started)
        seen["stored"] = list(source.stored)
        return AIMessage(content="图里是一张柱状图")

    env = make_env([answer])
    source = _VisualSource(env)
    runner = env.make_runner(attachment_source=lambda ctx: source)
    ctx = await _submit(env, "这张图是什么", [PNG])

    outcome = await env.run(ctx, runner=runner)

    assert outcome.status == "finished"
    assert seen == {"store_started": ["chart.png"], "stored": []}
    # The model input: the picture itself, and where it is in the workspace.
    text_block, image_block = _first_user_content(env)
    assert image_block == {"type": "image_url", "image_url": {"url": DATA_URL}}
    assert "<uploaded_images>" in text_block["text"]
    assert "- path: /uploads/chart.png\n  name: chart.png\n  raw: uploads/chart.png" in text_block["text"]
    # Not parsed as a document: nothing went through the document ingestion.
    assert source.ingested == []
    # The progress frame does not wait for the background write either.
    frames = _frames(await env.events())
    assert [f["data"]["status"] for f in frames] == ["start", "end"]
    assert "failed" not in frames[1]["data"]["extra_info"]
    assert "still_parsing" not in frames[1]["data"]["extra_info"]

    # The write goes on after the run and lands under the announced name.
    assert f"workspace/{CID}/uploads/chart.png" not in env.store.objects
    source.release()
    await _drain_background()
    assert env.store.objects[f"workspace/{CID}/uploads/chart.png"] == PNG_BYTES
    assert not direct_attachments._BACKGROUND


async def test_code_interpreter_hint_only_when_the_tool_is_bound(make_env):
    with_code = direct_attachments.render_image_listing(
        [("chart.png", direct_attachments.WorkspaceNames("/uploads/chart.png", "uploads/chart.png"))],
        [],
        has_code_interpreter=True,
    )
    without = direct_attachments.render_image_listing(
        [("chart.png", direct_attachments.WorkspaceNames("/uploads/chart.png", "uploads/chart.png"))],
        [],
        has_code_interpreter=False,
    )
    assert "bisheng_code_interpreter" in with_code
    assert "bisheng_code_interpreter" not in without and "read_file" in without
    assert direct_attachments.render_image_listing([], [], has_code_interpreter=True) == ""


async def test_images_and_documents_keep_distinct_planned_names(make_env):
    env = make_env([AIMessage(content="好的")])
    source = _VisualSource(env)
    source.release()
    runner = env.make_runner(attachment_source=lambda ctx: source)
    ctx = await _submit(env, "看看这些", [PNG, PDF, PNG_AGAIN])

    assert (await env.run(ctx, runner=runner)).status == "finished"
    await _drain_background()

    text = _first_user_content(env)[0]["text"]
    assert "- path: /uploads/chart.png\n  name: chart.png" in text
    assert "- path: /uploads/chart-2.png\n  name: chart.png" in text
    assert "/uploads/chart.md" not in text
    # The document still goes through the document ingestion; the images do not.
    assert source.ingested == ["b.pdf"]
    assert sorted(source.stored) == ["chart-2.png", "chart.png"]
    assert {f"workspace/{CID}/uploads/{n}" for n in ("chart.png", "chart-2.png", "b.md")} <= set(env.store.objects)


async def test_failed_write_is_logged_and_the_run_still_answers(make_env):
    env = make_env([AIMessage(content="图里是一张柱状图")])
    source = _VisualSource(env, store_error=OSError("bucket unreachable"))
    source.release()
    runner = env.make_runner(attachment_source=lambda ctx: source)
    ctx = await _submit(env, "这张图是什么", [PNG])
    lines: list[str] = []
    sink_id = logger.add(lambda m: lines.append(str(m)), level="ERROR", format="{message}")
    try:
        outcome = await env.run(ctx, runner=runner)
        await _drain_background()
    finally:
        logger.remove(sink_id)

    assert outcome.status == "finished"
    assert any("could not be written to the workspace uploads/" in line and "chart.png" in line for line in lines)
    # The model still got the picture, and the user is not told the attachment failed.
    assert _first_user_content(env)[1]["image_url"]["url"] == DATA_URL
    assert "failed" not in _frames(await env.events())[1]["data"]["extra_info"]
    assert f"workspace/{CID}/uploads/chart.png" not in env.store.objects


async def test_read_of_uploads_waits_for_the_image_write(make_env):
    """``read_file("/uploads/chart.png")`` in the same run returns the picture, not "not found"."""
    env = make_env([])
    source = _VisualSource(env)
    ctx = await _submit(env, "这张图是什么", [PNG])

    async def emit_frame(status: str, extra: dict) -> None:
        return None

    intake = direct_attachments.AttachmentIntake(ctx, ctx.files, source, emit_frame)
    reads: list[str] = []

    class _Backend:
        async def aread(self, path: str) -> str:
            reads.append(path)
            return "picture" if f"workspace/{CID}{path}" in env.store.objects else "not found"

    backend = _Backend()
    intake.guard(backend)
    await intake.start()
    view = await asyncio.wait_for(intake.first_view(), timeout=5)
    assert view.images == [DATA_URL] and not source.stored

    read = asyncio.create_task(backend.aread("/uploads/chart.png"))
    await asyncio.sleep(0.01)
    assert not read.done() and reads == []
    source.release()
    assert await asyncio.wait_for(read, timeout=5) == "picture"
    await intake.close()


async def test_refused_run_cancels_the_image_write(make_env):
    """A run that never starts its graph leaves nothing running in the background."""
    env = make_env([])
    source = _VisualSource(env)
    ctx = await _submit(env, "这张图是什么", [PNG])

    async def emit_frame(status: str, extra: dict) -> None:
        return None

    intake = direct_attachments.AttachmentIntake(ctx, ctx.files, source, emit_frame)
    await intake.start()
    await asyncio.sleep(0)
    await intake.close()
    await asyncio.sleep(0)

    assert not direct_attachments._BACKGROUND
    assert all(task.cancelled() or task.done() for task in intake._image_store_tasks.values())
    assert source.stored == []


async def test_non_visual_model_is_unchanged(make_env):
    """A model without vision: the image is parsed as a document, as before."""
    env = make_env([AIMessage(content="好的")], visual=False)
    source = _VisualSource(env)

    async def not_visual(ctx: DirectRunContext) -> bool:
        return False

    source.visual = not_visual
    runner = env.make_runner(attachment_source=lambda ctx: source)
    ctx = await _submit(env, "这张图是什么", [PNG])

    assert (await env.run(ctx, runner=runner)).status == "finished"

    content = next(m for m in env.model.inputs[0] if m.type == "human").content
    assert isinstance(content, str) and "<uploaded_images>" not in content
    assert source.ingested == ["chart.png"] and source.store_started == []


# ------------------------------------------------------------------- planning


def test_planned_names_of_directly_given_images():
    plans = direct_attachments.plan_workspace_names([PNG, PDF, PNG_AGAIN], originals={0, 2})

    assert (plans[0].path, plans[0].raw) == ("/uploads/chart.png", "uploads/chart.png")
    assert plans[1].path == "/uploads/b.md"
    assert (plans[2].path, plans[2].raw) == ("/uploads/chart-2.png", "uploads/chart-2.png")
    assert plans[2].seed >= {"chart.png"}
    # Without ``originals`` an image is planned as a parsed document, as before.
    assert direct_attachments.plan_workspace_names([PNG])[0].path == "/uploads/chart.md"


# ------------------------------------------------------- production source


async def test_production_source_stores_the_original_under_its_name(monkeypatch: pytest.MonkeyPatch, tmp_path):
    local = tmp_path / "downloaded.png"
    local.write_bytes(PNG_BYTES)

    async def download(url: str):
        assert url in (PNG["filepath"], PNG_AGAIN["filepath"])
        return str(local), "downloaded.png"

    monkeypatch.setattr(direct_attachments, "async_file_download", download)
    store = _Store()
    source = direct_attachments.WorkspaceAttachmentSource(object_store=lambda: _async(store), **LIMITS)
    ctx = DirectRunContext(conversation_id=CID, run_id="r1", tenant_id=TENANT, user_id=USER, files=[PNG, PNG_AGAIN])
    plans = direct_attachments.plan_workspace_names([PNG, PNG_AGAIN], originals={0, 1})

    first = await source.store_image(ctx, PNG, set(plans[0].seed))
    second = await source.store_image(ctx, PNG_AGAIN, set(plans[1].seed))

    # The planned names are the ones the write picks, whatever order the writes run in.
    assert first["workspace_path"] == plans[0].path == "/uploads/chart.png"
    assert second["workspace_path"] == plans[1].path == "/uploads/chart-2.png"
    assert first["valid"] is True and first["line_count"] == 0
    assert store.objects[f"workspace/{CID}/uploads/chart.png"] == PNG_BYTES
    assert store.objects[f"workspace/{CID}/uploads/chart-2.png"] == PNG_BYTES
    # Nothing was parsed: no markdown view exists.
    assert not any(key.endswith(".md") for key in store.objects)

    # A later run reads the picture with ``read_file``.
    backend = WorkspaceBackend(
        minio=store, file_dir=str(tmp_path / "cache"), workspace_prefix=f"workspace/{CID}", create_cache_dir=False
    )
    result = await backend.aread("/uploads/chart.png")
    assert result.error is None
    assert base64.standard_b64decode(result.file_data["content"]) == PNG_BYTES
