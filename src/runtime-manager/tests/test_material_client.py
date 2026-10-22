"""覆盖 AC: AC-07、AC-15、AC-26、AC-28、AC-42、AC-44、AC-46、AC-47、AC-52."""

import hashlib
import hmac
import json
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from runtime_manager import material_protocol as wire
from runtime_manager.config import Config
from runtime_manager.platform_protocol import canonical_message

D = "11111111-1111-4111-8111-111111111111"
UID = "22222222-2222-4222-8222-222222222222"
T = "33333333-3333-4333-8333-333333333333"
DATA = b"0123456789"


class Backend:
    def __init__(self):
        self.now = 100000
        self.key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        self.seen = set()
        self.calls = []
        self.uploaded = b""
        self.ticket = ""
        self.session = None
        self.confirmed = False
        self.lost_put = self.lost_finalize = self.lost_content = False
        self.expire_ticket = False
        self.deny = None
        self.bad_range = self.bad_digest = False

    def reply(self, request):
        proof = wire.verify_request(
            request.method,
            request.url.raw_path.decode(),
            request.content,
            request.headers,
            public_key=self.key.public_key(),
            now=self.now,
        )
        assert proof.nonce not in self.seen
        self.seen.add(proof.nonce)
        self.calls.append((request.method, request.url.raw_path.decode(), request.content))
        if self.deny:
            return httpx.Response(self.deny, json={"error": {"reason": "fixture_refused"}})
        if request.url.path.endswith("/exchange"):
            body = json.loads(request.content)
            self.ticket = uuid4().hex
            data = DATA if body["action"] == "download" else b""
            self.session = {
                "transfer_id": T,
                "artifact_id": body.get("artifact_id", "output-a"),
                "action": body["action"],
                "state": "confirmed" if self.confirmed else "open",
                "offset": len(self.uploaded),
                "sha256": hashlib.sha256(data).hexdigest() if body["action"] == "download" else body["sha256"],
                "size_bytes": len(data) if body["action"] == "download" else body["size_bytes"],
                "kind": body.get("kind", "compiled"),
                "platform": body.get("platform", ""),
                "ticket": self.ticket,
                "expires_at": self.now + 300,
            }
            return httpx.Response(200, json=self.session)
        if proof.ticket != self.ticket or self.expire_ticket:
            self.expire_ticket = False
            return httpx.Response(401, json={"error": {"reason": "material_ticket_expired"}})
        if request.method == "PUT":
            offset = int(request.url.params["offset"])
            assert offset == len(self.uploaded)
            self.uploaded += request.content
            if self.lost_put:
                self.lost_put = False
                raise httpx.ReadTimeout("fixture lost PUT response", request=request)
            return httpx.Response(200, json={"transfer_id": T, "offset": len(self.uploaded), "state": "open"})
        if request.url.path.endswith("/finalize"):
            self.confirmed = True
            if self.lost_finalize:
                self.lost_finalize = False
                raise httpx.ReadTimeout("fixture lost finalize response", request=request)
            return httpx.Response(200, json={**self.session, "state": "verified", "confirmed_at": "fixture-confirmed"})
        if request.url.path.endswith("/content"):
            offset, length = int(request.url.params["offset"]), int(request.url.params["length"])
            data = DATA[offset : offset + length]
            headers = {
                "Content-Length": str(len(data)),
                "Content-Range": f"bytes {offset}-{offset + len(data) - 1}/{len(DATA)}",
            }
            if self.bad_range:
                headers["Content-Range"] = "bytes 0-1/999"
            if self.bad_digest:
                data = b"x" * len(data)
            if self.lost_content:
                self.lost_content = False

                class Partial(httpx.SyncByteStream):
                    def __iter__(self):
                        yield data[:2]
                        raise httpx.ReadError("fixture partial response")

                return httpx.Response(206, headers=headers, stream=Partial())
            return httpx.Response(206, content=data, headers=headers)
        return httpx.Response(
            200,
            json={
                **{k: v for k, v in self.session.items() if k != "ticket"},
                "offset": len(self.uploaded),
                "state": "confirmed" if self.confirmed else "open",
                "confirmed_at": "fixture-confirmed" if self.confirmed else None,
            },
        )


@pytest.fixture
def client():
    from runtime_manager.material_client import MaterialClient

    server = Backend()
    client = MaterialClient(
        "https://backend",
        delegation_id=D,
        key_id="key-a",
        pod_uid=UID,
        private_key=server.key,
        deadline=server.now + 600,
        clock=lambda: server.now,
        sleep=lambda seconds: None,
        chunk_bytes=4,
        transport=httpx.MockTransport(server.reply),
    )
    try:
        yield client, server
    finally:
        client.close()


def download(c, path, **kwargs):
    return c.download(
        "compiled-a", path, expected_sha256=hashlib.sha256(DATA).hexdigest(), expected_size=len(DATA), **kwargs
    )


def test_download_checks_frozen_size_digest_and_preserves_atomic_target(client, tmp_path):
    c, b = client
    path = tmp_path / "artifact"
    result = download(c, path)
    assert path.read_bytes() == DATA and result["artifact_id"] == "compiled-a"
    assert len([x for x in b.calls if "/content?" in x[1]]) == 3
    assert all("x-runtime" not in str(x).lower() for x in b.calls)


def test_partial_download_block_is_discarded_and_retried_with_new_nonce(client, tmp_path):
    c, b = client
    b.lost_content = True
    path = tmp_path / "artifact"
    download(c, path)
    assert path.read_bytes() == DATA
    targets = [x[1] for x in b.calls if "/content?" in x[1]]
    assert targets[0] == targets[1] and len(targets) == 4


@pytest.mark.parametrize("bad", ["bad_range", "bad_digest"])
def test_bad_content_never_replaces_existing_target(client, tmp_path, bad):
    from runtime_manager.material_client import MaterialClientError

    c, b = client
    setattr(b, bad, True)
    path = tmp_path / "artifact"
    path.write_bytes(b"old")
    with pytest.raises(MaterialClientError):
        download(c, path)
    assert path.read_bytes() == b"old" and list(tmp_path.iterdir()) == [path]


def test_frozen_manifest_mismatch_is_rejected_before_content_download(client, tmp_path):
    from runtime_manager.material_client import MaterialClientError

    c, b = client
    with pytest.raises(MaterialClientError):
        c.download("compiled-a", tmp_path / "out", expected_sha256="f" * 64, expected_size=len(DATA))
    assert len(b.calls) == 1


def test_expired_ticket_is_reexchanged_without_changing_overall_deadline(client, tmp_path):
    c, b = client
    b.expire_ticket = True
    initial = c.deadline
    download(c, tmp_path / "out")
    assert len([x for x in b.calls if x[1].endswith("/exchange")]) == 2 and c.deadline == initial


def test_upload_lost_response_reads_offset_instead_of_appending_twice(client, tmp_path):
    c, b = client
    b.lost_put = True
    path = tmp_path / "content"
    path.write_bytes(DATA)
    result = c.upload(path, kind="compiled")
    assert result["state"] == "verified" and b.uploaded == DATA
    assert len([x for x in b.calls if x[0] == "PUT"]) == 3
    assert any(x[0] == "GET" and x[1].endswith(T) for x in b.calls)


def test_finalize_response_loss_recovers_confirmed_fact(client, tmp_path):
    c, b = client
    b.lost_finalize = True
    path = tmp_path / "content"
    path.write_bytes(DATA)
    result = c.upload(path, kind="snapshot", metadata={"format": "sqlite3", "integrity_result": "ok"})
    assert result["state"] == "verified" and result["confirmed_at"] and b.uploaded == DATA


@pytest.mark.parametrize("status", [403, 307])
def test_forbidden_and_redirect_are_not_retried(client, tmp_path, status):
    from runtime_manager.material_client import MaterialClientError

    c, b = client
    b.deny = status
    with pytest.raises(MaterialClientError):
        download(c, tmp_path / "out")
    assert len(b.calls) == 1


def test_unavailable_retry_is_bounded_and_does_not_change_deadline(client, tmp_path):
    from runtime_manager.material_client import MaterialClientError

    c, b = client
    b.deny = 503
    deadline = c.deadline
    with pytest.raises(MaterialClientError):
        download(c, tmp_path / "out")
    assert len(b.calls) <= 4 and c.deadline == deadline


def test_no_work_after_phase_deadline(client, tmp_path):
    from runtime_manager.material_client import MaterialClientError

    c, b = client
    b.now = c.deadline
    with pytest.raises(MaterialClientError):
        download(c, tmp_path / "out")
    assert b.calls == []


@pytest.mark.parametrize(
    "url", ["http://backend", "https://backend/private", "https://user:pass@backend", "https://backend?x=1"]
)
def test_material_client_requires_trusted_https_origin(url):
    from runtime_manager.material_client import MaterialClient, MaterialClientError

    with pytest.raises(MaterialClientError):
        MaterialClient(url, delegation_id=D, key_id="key-a", pod_uid=UID, private_key=Backend().key, deadline=200000)


def test_control_client_supports_node_bound_resource_and_material_interfaces():
    from runtime_manager.platform_client import PREFIX, PlatformClient

    calls = []

    def reply(request):
        message = canonical_message(
            request.method,
            request.url.path,
            request.content,
            int(request.headers["x-runtime-timestamp"]),
            request.headers["x-runtime-nonce"],
            "manager",
        )
        assert hmac.compare_digest(
            request.headers["x-runtime-signature"],
            hmac.new(b"fixture-control-key", message, hashlib.sha256).hexdigest(),
        )
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={"ok": True})

    c = PlatformClient(
        Config(platform_base_url="http://backend", platform_key_id="manager", platform_secret="fixture-control-key"),
        transport=httpx.MockTransport(reply),
    )
    try:
        assert c.claim_controller("holder-a", 0)["ok"]
        c.renew_controller("holder-a", 1)
        c.register_resource({"resource_ref": D})
        c.observe_resource(D, {"action": "bind"})
        c.create_material_delegation({"key_id": "public-only"})
        c.bind_material_delegation(D, UID)
    finally:
        c.close()
    assert [x[1] for x in calls] == [
        PREFIX + suffix
        for suffix in [
            "/controllers/claim",
            "/controllers/renew",
            "/resources",
            f"/resources/{D}/observations",
            "/material-delegations",
            f"/material-delegations/{D}/bind",
        ]
    ]


def test_material_manifest_is_obtained_from_the_authorized_backend_before_materialization(client):
    c, _ = client
    manifest = c.describe("compiled-a")
    assert manifest["sha256"] == hashlib.sha256(DATA).hexdigest() and manifest["size_bytes"] == len(DATA)
    assert "ticket" not in manifest


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), -1, True])
def test_invalid_phase_bounds_are_rejected(deadline):
    from runtime_manager.material_client import MaterialClient, MaterialClientError

    with pytest.raises(MaterialClientError):
        MaterialClient(
            "https://backend",
            delegation_id=D,
            key_id="key-a",
            pod_uid=UID,
            private_key=Backend().key,
            deadline=deadline,
        )


def test_renewal_cannot_silently_switch_to_another_transfer(client, tmp_path):
    from runtime_manager.material_client import MaterialClientError

    c, b = client
    original = b.reply
    exchanges = 0

    def reply(request):
        nonlocal exchanges
        response = original(request)
        if request.url.path.endswith("/exchange"):
            exchanges += 1
            if exchanges > 1:
                return httpx.Response(200, json={**response.json(), "transfer_id": str(uuid4())})
        return response

    c._http.close()
    c._http = httpx.Client(base_url="https://backend", transport=httpx.MockTransport(reply))
    b.expire_ticket = True
    with pytest.raises(MaterialClientError):
        download(c, tmp_path / "out")
    assert not (tmp_path / "out").exists()
