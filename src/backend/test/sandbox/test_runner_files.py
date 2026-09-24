"""Tar copy-in / copy-out protocol tests (F068 T009)."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile

import pytest
from app import create_app
from starlette.testclient import TestClient


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _open_tar(fileobj, mode: str):
    return tarfile.open(fileobj=fileobj, mode=mode, encoding="utf-8", format=tarfile.PAX_FORMAT)


def _tar_gz(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with _open_tar(buf, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _untar(payload: bytes) -> dict[str, bytes]:
    buf = io.BytesIO(payload)
    out: dict[str, bytes] = {}
    with _open_tar(buf, "r:gz") as tar:
        for member in tar:
            if member.isfile():
                fh = tar.extractfile(member)
                out[member.name.replace("\\", "/")] = fh.read() if fh else b""
    return out


@pytest.fixture
def client(tmp_path):
    app = create_app(
        token="test-token",
        sessions_root=str(tmp_path / "sessions"),
        max_copy_in_bytes=1024,
    )
    with TestClient(app) as http:
        yield http, app


def _session(client: TestClient) -> tuple[str, dict[str, str]]:
    body = client.post("/v1/sessions", headers=_auth()).json()
    return body["session_id"], {"X-Lease-Token": body["lease_token"]}


def test_put_requires_lease_token(client):
    http, _app = client
    sid, headers = _session(http)
    assert http.put(f"/v1/sessions/{sid}/files", content=_tar_gz({"a.txt": b"x"})).status_code in {401, 403, 404}
    ok = http.put(f"/v1/sessions/{sid}/files", headers=headers, content=_tar_gz({"a.txt": b"x"}))
    assert ok.status_code == 200


def test_zip_slip_rejected_and_does_not_escape(client, tmp_path):
    http, _app = client
    sid, headers = _session(http)
    outside = tmp_path / "escaped.txt"
    payload = _tar_gz({"../escaped.txt": b"nope"})
    resp = http.put(f"/v1/sessions/{sid}/files", headers=headers, content=payload)
    assert resp.status_code == 400
    assert not outside.exists()
    # nothing written under the sessions root outside the uuid dir
    for root, _dirs, files in os.walk(tmp_path / "sessions"):
        assert "escaped.txt" not in files


def test_md5_hit_does_not_overwrite(client):
    http, app = client
    sid, headers = _session(http)
    data = b"same-bytes"
    digest = _md5(data)
    manifest = json.dumps({"keep.txt": digest})
    headers = {**headers, "X-File-Manifest": manifest}
    assert (
        http.put(f"/v1/sessions/{sid}/files", headers=headers, content=_tar_gz({"keep.txt": data})).status_code == 200
    )
    lease = app.state.store._leases[sid]
    on_disk = os.path.join(lease.work_dir, "keep.txt")
    with open(on_disk, "w", encoding="utf-8") as fh:
        fh.write("mutated")
    again = http.put(f"/v1/sessions/{sid}/files", headers=headers, content=_tar_gz({"keep.txt": data}))
    assert again.status_code == 200
    assert open(on_disk, encoding="utf-8").read() == "mutated"


def test_get_is_recursive_diff_against_pre_exec_snapshot(client):
    http, _app = client
    sid, headers = _session(http)
    first = _tar_gz({"keep.txt": b"old"})
    http.put(f"/v1/sessions/{sid}/files", headers=headers, content=first)
    exec_resp = http.post(
        f"/v1/sessions/{sid}/exec",
        headers=headers,
        json={
            "code": "import pathlib\npathlib.Path('output/sub/a.txt').parent.mkdir(parents=True)\npathlib.Path('output/sub/a.txt').write_text('nested')\n",
            "lang": "python",
            "timeout_s": 5,
        },
    )
    assert exec_resp.status_code == 200
    assert exec_resp.json()["exitcode"] == 0
    got = http.get(f"/v1/sessions/{sid}/files", headers=headers)
    assert got.status_code == 200
    members = _untar(got.content)
    assert "output/sub/a.txt" in members
    assert members["output/sub/a.txt"] == b"nested"
    assert "keep.txt" not in members


def test_oversized_member_skipped_and_named(client):
    http, _app = client
    sid, headers = _session(http)
    big = b"x" * 2048
    small = b"ok"
    resp = http.put(
        f"/v1/sessions/{sid}/files",
        headers=headers,
        content=_tar_gz({"big.bin": big, "small.txt": small}),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert any(item["path"] == "big.bin" for item in body["skipped"])
    assert "small.txt" in body["written"]


def test_chinese_workspace_paths_round_trip_and_print(client):
    http, _app = client
    sid, headers = _session(http)
    rel = "uploads/工作台_工作流输入支持音视频.docx"
    payload = _tar_gz({rel: "中文内容".encode()})
    manifest = json.dumps({rel: _md5("中文内容".encode())}, ensure_ascii=True)
    put = http.put(
        f"/v1/sessions/{sid}/files",
        headers={**headers, "X-File-Manifest": manifest},
        content=payload,
    )
    assert put.status_code == 200
    assert rel in put.json()["written"]
    code = (
        "from pathlib import Path\n"
        "text = Path('uploads/工作台_工作流输入支持音视频.docx').read_text(encoding='utf-8')\n"
        "Path('output').mkdir(exist_ok=True)\n"
        "Path('output/报告.txt').write_text(text + '已处理', encoding='utf-8')\n"
        "print(text)\n"
    )
    exec_resp = http.post(
        f"/v1/sessions/{sid}/exec",
        headers=headers,
        json={"code": code, "lang": "python", "timeout_s": 5},
    )
    assert exec_resp.status_code == 200
    body = exec_resp.json()
    assert body["exitcode"] == 0
    assert "中文内容" in body["stdout"]
    got = http.get(f"/v1/sessions/{sid}/files", headers=headers)
    assert got.status_code == 200
    members = _untar(got.content)
    assert "output/报告.txt" in members
    assert members["output/报告.txt"] == "中文内容已处理".encode()
