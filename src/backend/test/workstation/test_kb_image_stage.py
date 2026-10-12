"""Knowledge-base images handed to the code interpreter (stage, annotate, limits)."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from bisheng.common.image_view import ImageRegistry
from bisheng.workstation.domain.services.chat_service import (
    _annotate_retrieved_chunk,
    _attach_kb_image_stage,
)
from bisheng.workstation.domain.services.kb_image_stage import KbImageStage

URL = "/bisheng/knowledge/images/1/27/img_1.png"
REL = "uploads/kb/1/27/img_1.png"


class _FakeResponse:
    def __init__(self, data: bytes, declare_length: bool = True):
        self._data = data
        self.headers = {"Content-Length": str(len(data))} if declare_length else {}
        self.closed = False
        self.released = False

    def stream(self, size):
        for i in range(0, len(self._data), size):
            yield self._data[i : i + size]

    def close(self):
        self.closed = True

    def release_conn(self):
        self.released = True


class _FakeClient:
    def __init__(self, objects: dict[str, bytes], declare_length: bool = True):
        self.objects = objects
        self.declare_length = declare_length
        self.calls: list[tuple[str, str]] = []

    def get_object(self, bucket, key):
        self.calls.append((bucket, key))
        if key not in self.objects:
            err = RuntimeError("missing")
            err.code = "NoSuchKey"
            raise err
        return _FakeResponse(self.objects[key], self.declare_length)


def _stage(**overrides) -> KbImageStage:
    kwargs = {"max_files": 100, "max_file_bytes": 1024, "max_total_bytes": 4096}
    kwargs.update(overrides)
    return KbImageStage("bisheng", **kwargs)


def test_annotate_keeps_markdown_and_appends_relative_path():
    stage = _stage()
    out = stage.annotate(f"see ![chart]({URL}) done")
    assert f"![chart]({URL})\u27e6file: {REL}\u27e7" in out
    assert stage.paths() == [REL]


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/a.png",
        "/other-bucket/knowledge/images/1/2/a.png",
        "/bisheng/knowledge/images/1/2/../a.png",
        "/bisheng/knowledge/images/x/2/a.png",
        "/bisheng/knowledge/images/1/2/a/b.png",
        "/bisheng/other/1/2/a.png",
    ],
)
def test_annotate_ignores_urls_that_are_not_knowledge_images(url):
    stage = _stage()
    text = f"![x]({url})"
    assert stage.annotate(text) == text
    assert len(stage) == 0


def test_same_image_registered_once():
    stage = _stage()
    stage.annotate(f"![a]({URL}) ![b]({URL}?x=1)")
    assert stage.paths() == [REL]


def test_annotate_runs_even_without_image_registry():
    stage = _stage()
    out = _annotate_retrieved_chunk(f"![a]({URL})", None, stage)
    assert REL in out and "img#" not in out


def test_annotate_runs_alongside_image_registry():
    stage = _stage()
    out = _annotate_retrieved_chunk(f"![a]({URL})", ImageRegistry(), stage)
    assert "\u27e6img#1\u27e7" in out and REL in out


def test_annotate_without_stage_is_unchanged():
    assert _annotate_retrieved_chunk(f"![a]({URL})", None) == f"![a]({URL})"


def test_materialize_writes_files(tmp_path):
    stage = _stage()
    stage.annotate(f"![a]({URL})")
    client = _FakeClient({"knowledge/images/1/27/img_1.png": b"PNG"})
    notice = stage.materialize(str(tmp_path), lambda: client)
    assert notice == ""
    assert (tmp_path / REL).read_bytes() == b"PNG"
    assert client.calls == [("bisheng", "knowledge/images/1/27/img_1.png")]
    assert not list(tmp_path.rglob("*.part"))


def test_materialize_skips_existing_file(tmp_path):
    stage = _stage()
    stage.annotate(f"![a]({URL})")
    target = tmp_path / REL
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    client = _FakeClient({})
    assert stage.materialize(str(tmp_path), lambda: client) == ""
    assert client.calls == []
    assert target.read_bytes() == b"old"


def test_materialize_reports_missing_object(tmp_path):
    stage = _stage()
    stage.annotate(f"![a]({URL})")
    notice = stage.materialize(str(tmp_path), lambda: _FakeClient({}))
    assert REL in notice and "not found" in notice
    assert not (tmp_path / REL).exists()


def test_materialize_reports_unavailable_storage(tmp_path):
    stage = _stage()
    stage.annotate(f"![a]({URL})")

    def _boom():
        raise RuntimeError("no endpoint")

    notice = stage.materialize(str(tmp_path), _boom)
    assert REL in notice and "not available" in notice


def test_materialize_without_entries_does_nothing(tmp_path):
    called = []
    assert _stage().materialize(str(tmp_path), lambda: called.append(1)) == ""
    assert called == []


def test_file_count_limit(tmp_path):
    stage = _stage(max_files=2)
    objects = {}
    for i in range(3):
        stage.annotate(f"![a](/bisheng/knowledge/images/1/27/i{i}.png)")
        objects[f"knowledge/images/1/27/i{i}.png"] = b"x"
    notice = stage.materialize(str(tmp_path), lambda: _FakeClient(objects))
    assert sorted(os.listdir(tmp_path / "uploads/kb/1/27")) == ["i0.png", "i1.png"]
    assert "i2.png" in notice and "limit of 2 images" in notice


@pytest.mark.parametrize("declare_length", [True, False])
def test_per_image_limit(tmp_path, declare_length):
    stage = _stage(max_file_bytes=4)
    stage.annotate(f"![a]({URL})")
    client = _FakeClient({"knowledge/images/1/27/img_1.png": b"12345"}, declare_length)
    notice = stage.materialize(str(tmp_path), lambda: client)
    assert "per-image limit" in notice
    assert not (tmp_path / REL).exists()
    assert not list(tmp_path.rglob("*.part"))


def test_total_bytes_limit(tmp_path):
    stage = _stage(max_file_bytes=10, max_total_bytes=15)
    objects = {}
    for i in range(3):
        stage.annotate(f"![a](/bisheng/knowledge/images/1/27/i{i}.png)")
        objects[f"knowledge/images/1/27/i{i}.png"] = b"x" * 8
    notice = stage.materialize(str(tmp_path), lambda: _FakeClient(objects))
    assert sorted(os.listdir(tmp_path / "uploads/kb/1/27")) == ["i0.png"]
    assert "total limit" in notice and "i1.png" in notice and "i2.png" in notice


def test_failure_advisory_only_when_code_mentions_object_path():
    stage = _stage()
    stage.annotate(f"![a]({URL})")
    assert stage.failure_advisory("print(1)") == ""
    advice = stage.failure_advisory("open('/bisheng/knowledge/images/1/27/img_1.png')")
    assert REL in advice


def test_from_settings_derives_total_from_max_copy_in(monkeypatch):
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.sandbox_conf, "max_copy_in_bytes", 1000)
    monkeypatch.setattr(settings.sandbox_conf, "kb_image_stage_max_total_bytes", 0)
    stage = KbImageStage.from_settings()
    assert stage.max_file_bytes == 1000
    assert stage.max_total_bytes == 5000
    assert stage.max_files == 100

    monkeypatch.setattr(settings.sandbox_conf, "kb_image_stage_max_total_bytes", 7)
    assert KbImageStage.from_settings().max_total_bytes == 7


class _FakeExecutor:
    supports_kb_stage = True

    def __init__(self):
        self.stage = None

    def attach_stage(self, stage):
        self.stage = stage

    @property
    def description(self):
        return "desc+hint" if self.stage is not None else "desc"


def test_attach_kb_image_stage_refreshes_both_descriptions():
    executor = _FakeExecutor()
    inner = SimpleNamespace(executor=executor, description="desc")
    wrapper = SimpleNamespace(tool_instance=inner, description="desc")
    _attach_kb_image_stage(wrapper, _stage())
    assert executor.stage is not None
    assert inner.description == "desc+hint"
    assert wrapper.description == "desc+hint"


def test_attach_kb_image_stage_ignores_tools_without_executor():
    tool = SimpleNamespace(description="x")
    _attach_kb_image_stage(tool, _stage())
    assert tool.description == "x"
