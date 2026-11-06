"""Sandbox runner protocol. These checks do not pass a BiSheng case."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile

import httpx
import pytest

from test.sandbox.release.env import SANDBOX_TOKEN

MAX_COPY_IN = 50 * 1024 * 1024


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _tar_gz(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", encoding="utf-8", format=tarfile.PAX_FORMAT) as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _framed(members: dict[str, bytes]) -> bytes:
    tar = _tar_gz(members)
    manifest = {name: _md5(data) for name, data in members.items()}
    raw = json.dumps(manifest, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return len(raw).to_bytes(4, "big") + raw + tar


def _untar(payload: bytes) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz", encoding="utf-8") as tar:
        for member in tar:
            if member.isfile():
                handle = tar.extractfile(member)
                out[member.name.replace("\\", "/")] = handle.read() if handle else b""
    return out


def _session(http: httpx.Client) -> tuple[str, dict[str, str]]:
    created = http.post("/v1/sessions", headers={"Authorization": f"Bearer {SANDBOX_TOKEN}"})
    assert created.status_code == 200, created.text
    body = created.json()
    return body["session_id"], {"X-Lease-Token": body["lease_token"]}


@pytest.fixture
def runner(sandbox_url: str):
    with httpx.Client(base_url=sandbox_url, timeout=60.0) as http:
        yield http


def test_runner_health_needs_no_token(runner: httpx.Client):
    assert runner.get("/health").status_code == 200


def test_runner_rejects_bad_token_and_separates_sessions(runner: httpx.Client):
    import os

    denied = runner.post("/v1/sessions", headers={"Authorization": "Bearer wrong-token"})
    assert denied.status_code == 401
    first, first_lease = _session(runner)
    second, second_lease = _session(runner)
    try:
        assert first != second
        first_dir = f"/tmp/sessions/{first}"
        second_dir = f"/tmp/sessions/{second}"
        if os.path.isdir(first_dir) and os.path.isdir(second_dir):
            assert os.path.realpath(first_dir) != os.path.realpath(second_dir)
    finally:
        runner.delete(f"/v1/sessions/{first}", headers=first_lease)
        runner.delete(f"/v1/sessions/{second}", headers=second_lease)


def test_runner_put_chinese_name_and_skips_oversize(runner: httpx.Client):
    session_id, lease = _session(runner)
    try:
        small = {"中文说明.txt": "说明".encode()}
        stored = runner.put(f"/v1/sessions/{session_id}/files", headers=lease, content=_framed(small))
        assert stored.status_code == 200, stored.text
        read_back = runner.post(
            f"/v1/sessions/{session_id}/exec",
            headers=lease,
            json={"code": "print(open('中文说明.txt',encoding='utf-8').read())", "lang": "python", "timeout_s": 30},
        )
        assert read_back.status_code == 200
        assert read_back.json()["stdout"].strip() == "说明"
        oversized = {"big.bin": b"\0" * (MAX_COPY_IN + 1)}
        skipped = runner.put(f"/v1/sessions/{session_id}/files", headers=lease, content=_framed(oversized))
        assert skipped.status_code == 200, skipped.text
        body = skipped.json()
        assert body["skipped"][0]["path"] == "big.bin"
        assert body["skipped"][0]["size"] == MAX_COPY_IN + 1
    finally:
        runner.delete(f"/v1/sessions/{session_id}", headers=lease)


def test_runner_exec_sum_and_child_env(runner: httpx.Client):
    session_id, lease = _session(runner)
    try:
        code = "import os\nprint(sum([1, 2, 3]))\nprint(os.environ.get('SANDBOX_PRIVATE', ''))"
        ran = runner.post(
            f"/v1/sessions/{session_id}/exec",
            headers=lease,
            json={"code": code, "lang": "python", "timeout_s": 30},
        )
        assert ran.status_code == 200, ran.text
        body = ran.json()
        assert body["exitcode"] == 0
        lines = body["stdout"].splitlines()
        assert lines[0] == "6"
        assert lines[-1] == ""
        missing = runner.post(
            f"/v1/sessions/{session_id}/exec",
            json={"code": "print(1)", "lang": "python", "timeout_s": 10},
        )
        assert missing.status_code == 403
    finally:
        runner.delete(f"/v1/sessions/{session_id}", headers=lease)


def test_runner_get_files_is_gzip_tar_of_changes(runner: httpx.Client):
    session_id, lease = _session(runner)
    try:
        put = runner.put(
            f"/v1/sessions/{session_id}/files",
            headers=lease,
            content=_framed({"keep.txt": b"same"}),
        )
        assert put.status_code == 200
        ran = runner.post(
            f"/v1/sessions/{session_id}/exec",
            headers=lease,
            json={"code": "open('new.txt','w').write('created')\n", "lang": "python", "timeout_s": 30},
        )
        assert ran.status_code == 200 and ran.json()["exitcode"] == 0
        fetched = runner.get(f"/v1/sessions/{session_id}/files", headers=lease)
        assert fetched.status_code == 200
        assert "gzip" in fetched.headers.get("content-type", "")
        members = _untar(fetched.content)
        assert members.get("new.txt") == b"created"
        assert "keep.txt" not in members
    finally:
        runner.delete(f"/v1/sessions/{session_id}", headers=lease)


def test_runner_deleted_session_is_not_executable(runner: httpx.Client):
    session_id, lease = _session(runner)
    runner.delete(f"/v1/sessions/{session_id}", headers=lease)
    ran = runner.post(
        f"/v1/sessions/{session_id}/exec",
        headers=lease,
        json={"code": "print(1)", "lang": "python", "timeout_s": 10},
    )
    assert ran.status_code == 404
