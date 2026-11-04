"""LocalExecutor writes staged knowledge images before the script runs."""

from __future__ import annotations

from bisheng.workstation.domain.services.kb_image_stage import KbImageStage
from bisheng_langchain.gpts.tools.code_interpreter.e2b_executor import E2bCodeExecutor
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LocalExecutor

URL = "/bisheng/knowledge/images/1/27/img_1.png"
REL = "uploads/kb/1/27/img_1.png"


class _Resp:
    headers: dict = {}

    def __init__(self, data: bytes):
        self._data = data

    def stream(self, size):
        yield self._data

    def close(self):
        pass

    def release_conn(self):
        pass


class _Client:
    def __init__(self, objects):
        self.objects = objects

    def get_object(self, bucket, key):
        if key not in self.objects:
            raise RuntimeError("missing")
        return _Resp(self.objects[key])


def _executor(objects, monkeypatch) -> LocalExecutor:
    stage = KbImageStage("bisheng", max_files=100, max_file_bytes=1024, max_total_bytes=4096)
    stage.annotate(f"![a]({URL})")
    exe = LocalExecutor(minio={"public_bucket": "bisheng"})
    monkeypatch.setattr(exe, "_minio_client", lambda: _Client(objects))
    exe.attach_stage(stage)
    return exe


def test_script_can_open_staged_image(monkeypatch):
    exe = _executor({"knowledge/images/1/27/img_1.png": b"PNGDATA"}, monkeypatch)
    result = exe.run(f"print(open('{REL}','rb').read().decode())")
    assert result["exitcode"] == 0
    assert "PNGDATA" in result["log"]
    # Inputs are not deliverables.
    assert not any("img_1.png" in str(f) for f in result["file_list"])


def test_missing_image_adds_notice_on_success(monkeypatch):
    exe = _executor({}, monkeypatch)
    result = exe.run("print('hi')")
    assert result["exitcode"] == 0
    assert REL in result["log"] and "NOT written" in result["log"]


def test_missing_image_adds_notice_on_failure(monkeypatch):
    exe = _executor({}, monkeypatch)
    result = exe.run(f"open('{REL}','rb')")
    assert result["exitcode"] != 0
    assert REL in result["log"] and "NOT written" in result["log"]


def test_failure_with_object_url_gets_advisory(monkeypatch):
    exe = _executor({"knowledge/images/1/27/img_1.png": b"x"}, monkeypatch)
    result = exe.run("open('knowledge/images/1/27/nope.png','rb')")
    assert result["exitcode"] != 0
    assert REL in result["log"]


def test_hint_only_when_stage_attached():
    exe = LocalExecutor(minio={})
    plain = exe.description
    assert "KNOWLEDGE-BASE IMAGES" not in plain
    exe.attach_stage(KbImageStage("bisheng", max_files=1, max_file_bytes=1, max_total_bytes=1))
    assert "KNOWLEDGE-BASE IMAGES" in exe.description


def test_no_stage_leaves_behaviour_unchanged():
    result = LocalExecutor(minio={}).run("print('ok')")
    assert result["exitcode"] == 0
    assert "NOT written" not in result["log"]


def test_e2b_ignores_stage():
    assert E2bCodeExecutor.supports_kb_stage is False
    exe = E2bCodeExecutor.__new__(E2bCodeExecutor)
    exe._kb_stage = None
    exe.attach_stage(object())
    assert exe._kb_stage is None
