"""ContainerExecutor + FakeRunnerClient contract (F068 T013). No real HTTP."""

from __future__ import annotations

import ast
import json
import socket
from pathlib import Path

import pytest
from fake_runner import FakeRunnerClient, _tar_gz

from bisheng.common.errcode.sandbox import (
    SandboxCapacityExceededError,
    SandboxExecTimeoutError,
    SandboxProtocolError,
    SandboxUnreachableError,
)
from bisheng_langchain.gpts.tools.code_interpreter.container_executor import ContainerExecutor
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LocalExecutor

_SHUFFLE_MODULE = "bisheng_langchain.gpts.tools.code_interpreter.container_executor.random.shuffle"


def _exe(fake: FakeRunnerClient, **kwargs) -> ContainerExecutor:
    opts = {
        "minio": {},
        "endpoints": ["http://runner-a:8080"],
        "token": "test-token",
        "client": fake,
        "keep_session": False,
    }
    opts.update(kwargs)
    return ContainerExecutor(**opts)


def _posts(fake: FakeRunnerClient) -> list[str]:
    return [url for method, url in fake.calls if method == "POST" and url.rstrip("/").endswith("/v1/sessions")]


def test_fake_respects_path_params_across_sessions():
    fake = FakeRunnerClient()
    fake.add_replica("http://runner-a:8080")
    headers = {"Authorization": "Bearer test-token"}
    a = fake.request("POST", "http://runner-a:8080/v1/sessions", headers=headers).json()
    b = fake.request("POST", "http://runner-a:8080/v1/sessions", headers=headers).json()
    fake.request(
        "PUT",
        f"http://runner-a:8080/v1/sessions/{a['session_id']}/files",
        headers={"X-Lease-Token": a["lease_token"]},
        content=_tar_gz({"only-a.txt": b"secret-a", "output/sub/nested.txt": b"deep"}),
    )
    files_a = fake.session_files(a["session_id"])
    files_b = fake.session_files(b["session_id"])
    assert files_a["only-a.txt"] == b"secret-a"
    assert files_a["output/sub/nested.txt"] == b"deep"
    assert "only-a.txt" not in files_b
    assert "output/sub/nested.txt" not in files_b


def test_endpoints_skip_dns_shuffle_503_failover_then_all_503(tmp_path, monkeypatch):
    monkeypatch.setattr(_SHUFFLE_MODULE, lambda seq: None)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(AssertionError("DNS skipped")))

    fake = FakeRunnerClient()
    fake.add_replica("http://runner-a:8080", always_503=True)
    fake.add_replica("http://runner-b:8080")
    exe = _exe(fake, endpoints=["http://runner-a:8080", "http://runner-b:8080"])
    exitcode, logs, _ = exe.execute_code("print(1)", work_dir=str(tmp_path))
    assert exitcode == 0
    assert "ok" in logs
    assert _posts(fake) == [
        "http://runner-a:8080/v1/sessions",
        "http://runner-b:8080/v1/sessions",
    ]

    full = FakeRunnerClient()
    full.add_replica("http://runner-a:8080", always_503=True)
    full.add_replica("http://runner-b:8080", always_503=True)
    blocked = _exe(full, endpoints=["http://runner-a:8080", "http://runner-b:8080"])
    with pytest.raises(SandboxCapacityExceededError) as cap:
        blocked.execute_code("print(1)", work_dir=str(tmp_path))
    assert cap.value.Code == 28002
    assert cap.value.Code != SandboxUnreachableError.Code
    assert cap.value.Code != SandboxExecTimeoutError.Code
    assert cap.value.Code != SandboxProtocolError.Code


def test_all_replicas_unreachable_is_28001(tmp_path):
    fake = FakeRunnerClient()
    fake.add_replica("http://runner-a:8080", reachable=False)
    fake.add_replica("http://runner-b:8080", reachable=False)
    exe = _exe(fake, endpoints=["http://runner-a:8080", "http://runner-b:8080"])
    with pytest.raises(SandboxUnreachableError) as err:
        exe.execute_code("print(1)", work_dir=str(tmp_path))
    assert err.value.Code == 28001
    assert err.value.Code != SandboxCapacityExceededError.Code


def test_success_result_shape_matches_local_fields(tmp_path):
    fake = FakeRunnerClient()
    fake.add_replica("http://runner-a:8080", write_after_exec={"output/sub/a.txt": b"nested"})
    exe = _exe(fake, local_sync_path=str(tmp_path), keep_session=True)
    exe.upload_minio = lambda object_name, file_path: f"https://files/{Path(file_path).name}"
    result = exe.run("print('ok')")
    assert set(result) == {"exitcode", "log", "file_list"}
    assert result["exitcode"] == 0
    assert "ok" in result["log"]
    assert isinstance(result["file_list"], list)
    assert (tmp_path / "output" / "sub" / "a.txt").read_bytes() == b"nested"
    assert result["file_list"] == ["https://files/a.txt"]


def test_copy_in_scans_skills_skips_oversized_and_records_bytes(tmp_path):
    skill = tmp_path / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("skill-body")
    (tmp_path / "skills" / "huge.bin").write_bytes(b"x" * 400)

    fake = FakeRunnerClient()
    fake.add_replica("http://runner-a:8080")
    exe = _exe(
        fake,
        local_sync_path=str(tmp_path),
        keep_session=True,
        max_copy_in_bytes=100,
    )
    result = exe.run("print('ok')")
    assert result["exitcode"] == 0
    assert "skills/demo/SKILL.md" in fake.last_put_members
    assert "skills/huge.bin" not in fake.last_put_members
    assert "huge.bin" in result["log"]
    assert "Copy-in skipped an oversized file" in result["log"]
    assert exe.copy_in_bytes > 0
    assert exe.copy_in_bytes < 400


def test_keep_session_second_exec_reuses_bound_url(tmp_path, monkeypatch):
    monkeypatch.setattr(_SHUFFLE_MODULE, lambda seq: None)
    fake = FakeRunnerClient()
    fake.add_replica("http://runner-a:8080")
    fake.add_replica("http://runner-b:8080")
    exe = _exe(
        fake,
        endpoints=["http://runner-a:8080", "http://runner-b:8080"],
        keep_session=True,
        local_sync_path=str(tmp_path),
    )
    first = exe.execute_code("print(1)", work_dir=str(tmp_path))
    second = exe.execute_code("print(2)", work_dir=str(tmp_path))
    assert first[0] == 0 and second[0] == 0
    assert _posts(fake) == ["http://runner-a:8080/v1/sessions"]
    execs = [url for method, url in fake.calls if method == "POST" and url.endswith("/exec")]
    assert len(execs) == 2
    assert all(url.startswith("http://runner-a:8080/") for url in execs)
    assert not any(method == "DELETE" for method, _url in fake.calls)
    exe.close()
    assert any(method == "DELETE" and url.startswith("http://runner-a:8080/") for method, url in fake.calls)


def test_protocol_garbage_is_28006_and_never_local_executor(tmp_path, monkeypatch):
    fake = FakeRunnerClient()
    fake.add_replica("http://runner-a:8080", protocol_garbage=True)
    exe = _exe(fake)

    def _boom(*_a, **_k):
        raise AssertionError("LocalExecutor subprocess must not run")

    monkeypatch.setattr(LocalExecutor, "_execute_code", _boom)
    with pytest.raises(SandboxProtocolError) as err:
        exe.execute_code("print(1)", work_dir=str(tmp_path))
    assert err.value.Code == 28006
    assert err.value.Code != SandboxUnreachableError.Code
    assert err.value.Code != SandboxCapacityExceededError.Code
    assert err.value.Code != SandboxExecTimeoutError.Code


def test_exec_timeout_maps_to_28003(tmp_path):
    fake = FakeRunnerClient()
    fake.add_replica("http://runner-a:8080", exec_timeout=True)
    exe = _exe(fake)
    with pytest.raises(SandboxExecTimeoutError) as err:
        exe.execute_code("while True: pass", work_dir=str(tmp_path))
    assert err.value.Code == 28003
    assert err.value.Code != SandboxUnreachableError.Code
    assert err.value.Code != SandboxCapacityExceededError.Code
    assert err.value.Code != SandboxProtocolError.Code


def test_description_lists_isolation_libraries():
    fake = FakeRunnerClient()
    fake.add_replica("http://runner-a:8080")
    text = _exe(fake).description
    lowered = text.lower()
    assert "pandas" in lowered
    assert "openpyxl" in lowered
    assert "python-pptx" in lowered
    assert "pymupdf" in lowered
    assert "skills/" in text


def test_container_executor_has_no_orchestrator_imports_or_discover():
    path = (
        Path(__file__).resolve().parents[2]
        / "bisheng_langchain"
        / "gpts"
        / "tools"
        / "code_interpreter"
        / "container_executor.py"
    )
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    banned = {"docker", "kubernetes"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] not in banned for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in banned
    assert "def discover" not in source


def test_copy_in_keeps_chinese_paths_and_ascii_manifest(tmp_path):
    rel = "uploads/工作台_工作流输入支持音视频.docx"
    dest = tmp_path / Path(rel)
    dest.parent.mkdir(parents=True)
    dest.write_bytes("中文内容".encode())
    fake = FakeRunnerClient()
    fake.add_replica("http://runner-a:8080")
    exe = _exe(fake, local_sync_path=str(tmp_path), keep_session=True)
    result = exe.run("print('ok')")
    assert result["exitcode"] == 0
    assert rel in fake.last_put_members
    header = json.dumps({rel: "deadbeef"}, ensure_ascii=True)
    header.encode("ascii")
    assert "\\u" in header


def test_execute_code_without_work_dir_does_not_copy_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "secret-from-cwd.py").write_text("should-not-be-uploaded")
    fake = FakeRunnerClient()
    fake.add_replica("http://runner-a:8080")
    exe = _exe(fake)
    exitcode, logs, _ = exe.execute_code("print(1)")
    assert exitcode == 0
    assert "ok" in logs
    assert exe.copy_in_bytes == 0
    assert "secret-from-cwd.py" not in fake.last_put_members
    assert not any(method == "PUT" and url.endswith("/files") for method, url in fake.calls)
    assert not any(method == "GET" and url.endswith("/files") for method, url in fake.calls)
