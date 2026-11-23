"""F016: helpers that collect and promote the files the code interpreter leaves under output/.

See features/v3.1.0-beta1/016-daily-chat-generated-files/design.md decisions 1, 2, 6.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.workstation.domain.services import chat_service


def _entry(path: str, url: str | None = None, size: int = 3) -> dict:
    name = path.rsplit("/", 1)[-1]
    return {"path": path, "name": name, "size": size, "url": url or f"http://h/tmp-dir/{name}.obj?sig"}


def _code_tool(entries: list[dict]):
    executor = SimpleNamespace(collect_deliverables=True, published_deliverables=entries)
    return SimpleNamespace(name="bisheng_code_interpreter", description="code", executor=executor)


# ---------------------------------------------------------------- pure helpers


def test_enable_sets_flag_and_appends_hint():
    inner = SimpleNamespace(description="Run python.", executor=SimpleNamespace(collect_deliverables=False))
    wrapper = SimpleNamespace(description="Run python.", tool_instance=inner)

    chat_service._enable_deliverable_collection(wrapper)

    assert inner.executor.collect_deliverables is True
    assert inner.description.startswith("Run python.")
    assert "attached to your reply automatically" in inner.description
    assert wrapper.description == inner.description


def test_enable_keeps_e2b_sandbox_for_the_turn():
    executor = SimpleNamespace(collect_deliverables=False, keep_sandbox=False)
    tool = SimpleNamespace(description="Run python.", executor=executor)

    chat_service._enable_deliverable_collection(tool)

    assert executor.keep_sandbox is True


def test_enable_leaves_executors_without_keep_sandbox_alone():
    executor = SimpleNamespace(collect_deliverables=False)

    chat_service._enable_deliverable_collection(SimpleNamespace(description="Run python.", executor=executor))

    assert not hasattr(executor, "keep_sandbox")


def test_enable_ignores_tools_without_collection():
    tool = SimpleNamespace(description="search", executor=SimpleNamespace())

    chat_service._enable_deliverable_collection(tool)

    assert tool.description == "search"


def test_collect_dedup_keeps_last():
    tool = _code_tool(
        [_entry("output/a.docx", "http://h/tmp-dir/v1.docx"), _entry("output/a.docx", "http://h/tmp-dir/v2.docx")]
    )

    files = chat_service._collect_generated_files([tool])

    assert [f["filepath"] for f in files] == ["http://h/tmp-dir/v2.docx"]


def test_collect_caps_last_50():
    tool = _code_tool([_entry(f"output/f{i:02d}.txt") for i in range(60)])

    files = chat_service._collect_generated_files([tool])

    assert len(files) == chat_service.GENERATED_FILES_LIMIT == 50
    assert files[0]["path"] == "output/f10.txt"
    assert files[-1]["path"] == "output/f59.txt"


def test_item_shape():
    tool = _code_tool([_entry("output/北京今日天气.docx", "http://h/tmp-dir/x.docx?sig", size=12)])

    (item,) = chat_service._collect_generated_files([tool, SimpleNamespace(name="web_search")])

    assert len(item["file_id"]) == 32
    assert item == {
        "file_id": item["file_id"],
        "file_name": "北京今日天气.docx",
        "path": "output/北京今日天气.docx",
        "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "size": 12,
        "source": "code_interpreter",
        "filepath": "http://h/tmp-dir/x.docx?sig",
    }


@pytest.fixture
def storage(monkeypatch):
    client = MagicMock()
    client.tmp_bucket = "tmp-dir"
    client.bucket = "bisheng"

    async def copy_object(*, source_object, **_):
        if source_object.startswith("broken"):
            raise RuntimeError("copy failed")

    client.copy_object = AsyncMock(side_effect=copy_object)
    monkeypatch.setattr("bisheng.core.storage.chat_attachment.get_minio_storage", AsyncMock(return_value=client))
    return client


async def test_promote_partial_failure_keeps_others(storage):
    tool = _code_tool(
        [
            _entry("output/a.docx", "http://h/tmp-dir/broken.docx?sig"),
            _entry("output/b.xlsx", "http://h/tmp-dir/ok.xlsx?sig"),
        ]
    )

    files = await chat_service._promote_generated_files([tool], "chat-1", 7, "t1-7")

    assert len(files) == 2
    assert "object_name" not in files[0]
    assert files[0]["filepath"] == "http://h/tmp-dir/broken.docx?sig"
    assert files[1]["object_name"]


async def test_promoted_item_has_object_name(storage):
    tool = _code_tool([_entry("output/b.xlsx", "http://h/tmp-dir/ok.xlsx?sig")])

    (item,) = await chat_service._promote_generated_files([tool], "chat-1", 7, "t1-7")

    assert item["object_name"].startswith("chat/t1-7/")
    assert item["object_name"].endswith(".xlsx")
    assert storage.copy_object.await_args.kwargs["source_object"] == "ok.xlsx"
    # Kept so the card stays clickable; opening re-signs from object_name.
    assert item["filepath"] == "http://h/tmp-dir/ok.xlsx?sig"
