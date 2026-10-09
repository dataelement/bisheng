"""In-memory code-runner HTTP stand-in (F068 T013). Must respect URL path params."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse


class FakeUnreachableError(ConnectionError):
    """Raised when a replica is marked unreachable — same class family as a TCP miss."""


class FakeResponse:
    """Subset of ``httpx.Response`` that ``ContainerExecutor`` actually reads."""

    def __init__(
        self,
        status_code: int,
        *,
        json_data=None,
        content: bytes = b"",
        text: str | None = None,
        headers: dict | None = None,
    ):
        self.status_code = status_code
        self._json = json_data
        self._json_missing = json_data is None and text is not None
        if text is not None:
            self.content = text.encode("utf-8") if isinstance(text, str) else text
            self.text = text if isinstance(text, str) else text.decode("utf-8", "replace")
        elif json_data is not None:
            encoded = json.dumps(json_data).encode("utf-8")
            self.content = encoded
            self.text = encoded.decode("utf-8")
        else:
            self.content = content
            self.text = content.decode("utf-8", "replace")
        self.headers = headers or {}

    def json(self):
        if self._json_missing:
            raise json.JSONDecodeError("fake garbage", self.text, 0)
        if self._json is None:
            return json.loads(self.content.decode("utf-8") or "null")
        return self._json


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _path(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return path or "/"


def _open_tar(fileobj, mode: str):
    return tarfile.open(fileobj=fileobj, mode=mode, encoding="utf-8", format=tarfile.PAX_FORMAT)


def _tar_gz(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with _open_tar(buf, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name.replace("\\", "/"))
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _untar(payload: bytes) -> dict[str, bytes]:
    if not payload:
        return {}
    buf = io.BytesIO(payload)
    out: dict[str, bytes] = {}
    try:
        tar = _open_tar(buf, "r:gz")
    except tarfile.TarError:
        buf.seek(0)
        tar = _open_tar(buf, "r:")
    with tar:
        for member in tar:
            if not member.isfile():
                continue
            rel = member.name.replace("\\", "/")
            while rel.startswith("./"):
                rel = rel[2:]
            parts = rel.split("/")
            if rel.startswith("/") or any(part == ".." for part in parts):
                continue
            rel = "/".join(p for p in parts if p not in ("", "."))
            if not rel:
                continue
            fh = tar.extractfile(member)
            out[rel] = fh.read() if fh else b""
    return out


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


@dataclass
class FakeSession:
    session_id: str
    lease_token: str
    files: dict[str, bytes] = field(default_factory=dict)
    md5_index: dict[str, str] = field(default_factory=dict)
    copy_out_allowed: bool = False
    changed: dict[str, bytes] = field(default_factory=dict)


@dataclass
class FakeReplica:
    base_url: str
    token: str = "test-token"
    reachable: bool = True
    always_503: bool = False
    protocol_garbage: bool = False
    exec_timeout: bool = False
    max_sessions: int = 32
    write_after_exec: dict[str, bytes] = field(default_factory=dict)
    exec_stdout: str = "ok\n"
    sessions: dict[str, FakeSession] = field(default_factory=dict)

    def create_session(self) -> FakeSession:
        session = FakeSession(session_id=str(uuid.uuid4()), lease_token=uuid.uuid4().hex)
        self.sessions[session.session_id] = session
        return session


class FakeRunnerClient:
    """HTTP client whose store is keyed by ``(origin, session_id, path)``.

    A PUT to ``/v1/sessions/A/files`` must never surface on session B — that is
    pitfall 12 (E2B ``files.list`` defaulting to one directory level / ignoring
    the path). Nested copy-out members such as ``output/sub/a.txt`` are kept.
    """

    def __init__(self):
        self.replicas: dict[str, FakeReplica] = {}
        self.calls: list[tuple[str, str]] = []
        self.last_put_members: list[str] = []
        self.last_put_bytes: int = 0

    def add_replica(self, base_url: str, **kwargs) -> FakeReplica:
        replica = FakeReplica(base_url=base_url.rstrip("/"), **kwargs)
        self.replicas[_origin(replica.base_url)] = replica
        return replica

    def session_files(self, session_id: str) -> dict[str, bytes]:
        for replica in self.replicas.values():
            session = replica.sessions.get(session_id)
            if session is not None:
                return dict(session.files)
        return {}

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        content: bytes | None = None,
        json: dict | None = None,
        timeout=None,
    ) -> FakeResponse:
        del timeout
        method = method.upper()
        self.calls.append((method, url))
        origin = _origin(url)
        replica = self.replicas.get(origin)
        if replica is None or not replica.reachable:
            raise FakeUnreachableError(f"unreachable {origin}")
        path = _path(url)
        header_map = {str(k).lower(): v for k, v in (headers or {}).items()}

        if path == "/health" and method == "GET":
            return FakeResponse(200, json_data={"status": "ok"})

        if path == "/v1/sessions" and method == "POST":
            return self._create(replica, header_map)

        parts = path.split("/")
        # /v1/sessions/{id} or /v1/sessions/{id}/files or /v1/sessions/{id}/exec
        if len(parts) >= 4 and parts[1] == "v1" and parts[2] == "sessions":
            session_id = parts[3]
            rest = parts[4:]
            session = replica.sessions.get(session_id)
            if session is None:
                return FakeResponse(404, json_data={"error": "not found"})
            lease = (header_map.get("x-lease-token") or "").strip()
            if lease != session.lease_token:
                return FakeResponse(403, json_data={"error": "forbidden"})
            if not rest and method == "DELETE":
                replica.sessions.pop(session_id, None)
                return FakeResponse(200, json_data={"ok": True})
            if rest == ["files"] and method == "PUT":
                return self._put_files(session, header_map, content or b"")
            if rest == ["files"] and method == "GET":
                return self._get_files(session)
            if rest == ["exec"] and method == "POST":
                return self._exec(replica, session, json or {})
        return FakeResponse(404, json_data={"error": "not found"})

    def _create(self, replica: FakeReplica, header_map: dict) -> FakeResponse:
        auth = (header_map.get("authorization") or "").strip()
        expected = f"Bearer {replica.token}"
        if replica.token and auth != expected:
            return FakeResponse(401, json_data={"error": "unauthorized"})
        if replica.always_503 or len(replica.sessions) >= replica.max_sessions:
            return FakeResponse(503, json_data={"error": "capacity exceeded"})
        session = replica.create_session()
        expires = datetime.now(UTC) + timedelta(seconds=900)
        return FakeResponse(
            200,
            json_data={
                "session_id": session.session_id,
                "lease_token": session.lease_token,
                "lease_expires_at": expires.isoformat().replace("+00:00", "Z"),
            },
        )

    def _put_files(self, session: FakeSession, header_map: dict, body: bytes) -> FakeResponse:
        raw_manifest = header_map.get("x-file-manifest") or "{}"
        try:
            manifest = json.loads(raw_manifest)
        except json.JSONDecodeError:
            return FakeResponse(400, json_data={"error": "invalid manifest"})
        if not isinstance(manifest, dict):
            return FakeResponse(400, json_data={"error": "invalid manifest"})
        members = _untar(body)
        self.last_put_members = list(members)
        self.last_put_bytes = sum(len(v) for v in members.values())
        written: list[str] = []
        skipped: list[dict] = []
        for rel, data in members.items():
            expected = manifest.get(rel)
            if expected and session.md5_index.get(rel) == expected:
                continue
            session.files[rel] = data
            session.md5_index[rel] = expected or _md5(data)
            written.append(rel)
        return FakeResponse(200, json_data={"written": written, "skipped": skipped})

    def _get_files(self, session: FakeSession) -> FakeResponse:
        if not session.copy_out_allowed:
            return FakeResponse(200, content=_tar_gz({}))
        return FakeResponse(200, content=_tar_gz(session.changed))

    def _exec(self, replica: FakeReplica, session: FakeSession, payload: dict) -> FakeResponse:
        del payload
        if replica.protocol_garbage:
            return FakeResponse(200, text="{{not-json")
        if replica.exec_timeout:
            session.copy_out_allowed = False
            session.changed = {}
            return FakeResponse(
                200,
                json_data={"exitcode": 124, "stdout": "", "stderr": "", "duration_ms": 1},
            )
        session.copy_out_allowed = True
        session.changed = dict(replica.write_after_exec)
        session.files.update(session.changed)
        return FakeResponse(
            200,
            json_data={
                "exitcode": 0,
                "stdout": replica.exec_stdout,
                "stderr": "",
                "duration_ms": 1,
            },
        )
