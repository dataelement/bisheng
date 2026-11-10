"""覆盖 AC: AC-15、AC-46、AC-47. material-v1 fixed wire and Ed25519 verification."""

import hashlib

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

MODULE = "bisheng.app_runtime.domain.services.runtime_material_protocol"
P = "/internal/app-runtime/v2/material-access"
TARGET = P + "/transfers/33333333-3333-4333-8333-333333333333/content?length=1048576&offset=0"
NOW = 1792531200
IDENTITY = {
    "delegation_id": "11111111-1111-4111-8111-111111111111",
    "key_id": "material-v1-01",
    "pod_uid": "22222222-2222-4222-8222-222222222222",
    "timestamp": NOW,
    "nonce": "000102030405060708090a0b0c0d0e0f",
    "ticket": "example-ticket",
}


@pytest.fixture
def codec():
    import importlib

    return importlib.import_module(MODULE)


@pytest.fixture
def signer():
    return Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


@pytest.fixture
def headers(codec, signer):
    return codec.signed_headers("GET", TARGET, b"", private_key=signer, **IDENTITY)


def test_fixed_eleven_line_encoding_vector(codec):
    raw = codec.canonical_message("GET", TARGET, b"", **IDENTITY)
    assert len(raw) == 414 and len(raw.split(b"\n")) == 11 and not raw.endswith(b"\n")
    assert hashlib.sha256(raw).hexdigest() == "206cf7e08bc12e23245980c45989fe8165233183e18bed03b99a8c17c6050167"


def test_real_ed25519_signature_and_public_key(codec, signer, headers):
    proof = codec.verify_request(
        "GET", TARGET, b"", headers, public_key=signer.public_key().public_bytes_raw(), now=NOW
    )
    assert proof.delegation_id == IDENTITY["delegation_id"] and proof.pod_uid == IDENTITY["pod_uid"]
    assert "example-ticket" not in repr(proof)
    signature = bytes.fromhex(headers["X-Material-Signature"])
    assert len(signature) == 64
    signer.public_key().verify(signature, codec.canonical_message("GET", TARGET, b"", **IDENTITY))


@pytest.mark.parametrize("change", ["method", "path", "offset", "length", "body", "ticket", "pod", "nonce", "digest"])
def test_signed_fields_cannot_be_modified(codec, signer, headers, change):
    method, target, body = "GET", TARGET, b""
    if change == "method":
        method = "PUT"
        target = TARGET.split("?")[0] + "?offset=0"
        body = b"changed"
    elif change == "path":
        target = target.replace("33333333-3333", "43333333-3333")
    elif change == "offset":
        target = target.replace("offset=0", "offset=1")
    elif change == "length":
        target = target.replace("length=1048576", "length=1048575")
    elif change == "body":
        body = b"changed"
    elif change == "ticket":
        headers["X-Material-Ticket"] = "other-ticket"
    elif change == "pod":
        headers["X-Material-Pod-Uid"] = "42222222-2222-4222-8222-222222222222"
    elif change == "nonce":
        headers["X-Material-Nonce"] = "f" * 32
    elif change == "digest":
        headers["X-Material-Content-Sha256"] = "f" * 64
    with pytest.raises(codec.MaterialProtocolError):
        codec.verify_request(method, target, body, headers, public_key=signer.public_key(), now=NOW)


@pytest.mark.parametrize(
    "target",
    [
        TARGET + "&offset=0",
        TARGET + "&other=1",
        TARGET.replace("offset=0", "offset=00"),
        TARGET.replace("/transfers/", "//transfers/"),
        TARGET.replace("/content?", "/content/?"),
        TARGET.replace("/content?", "/%63ontent?"),
        TARGET.replace("length=1048576", "length=16777217"),
        TARGET.replace("length=1048576&offset=0", "offset=0&length=1048576"),
    ],
)
def test_ambiguous_paths_and_noncanonical_queries_are_refused(codec, signer, headers, target):
    with pytest.raises(codec.MaterialProtocolError):
        codec.verify_request("GET", target, b"", headers, public_key=signer.public_key(), now=NOW)


def test_client_can_explicitly_canonicalize_query_order(codec):
    assert codec.canonical_target("GET", TARGET.replace("length=1048576&offset=0", "offset=0&length=1048576")) == TARGET


@pytest.mark.parametrize("delta,accepted", [(59, True), (-59, True), (60, False), (-60, False)])
def test_timestamp_boundary_is_strictly_under_sixty_seconds(codec, signer, headers, delta, accepted):
    if accepted:
        assert codec.verify_request("GET", TARGET, b"", headers, public_key=signer.public_key(), now=NOW + delta)
    else:
        with pytest.raises(codec.MaterialProtocolError) as error:
            codec.verify_request("GET", TARGET, b"", headers, public_key=signer.public_key(), now=NOW + delta)
        assert error.value.status_code == 401


def test_duplicate_authentication_headers_and_mixed_service_auth_are_rejected(codec, signer, headers):
    raw = list(headers.items())
    raw.append(("x-material-key-id", IDENTITY["key_id"]))
    for values in (
        raw,
        [*headers.items(), ("X-Runtime-Key-Id", "manager")],
        [*headers.items(), ("Authorization", "Bearer fake")],
    ):
        with pytest.raises(codec.MaterialProtocolError):
            codec.verify_request("GET", TARGET, b"", values, public_key=signer.public_key(), now=NOW)


def test_exchange_has_no_ticket_and_signs_actual_json_bytes(codec, signer):
    body = b'{"action":"download","artifact_id":"artifact-legacy"}'
    identity = {**IDENTITY, "ticket": ""}
    signed = codec.signed_headers("POST", P + "/exchange", body, private_key=signer, **identity)
    assert "X-Material-Ticket" not in signed
    assert codec.verify_request("POST", P + "/exchange", body, signed, public_key=signer.public_key(), now=NOW)
    signed["X-Material-Ticket"] = "forbidden"
    with pytest.raises(codec.MaterialProtocolError):
        codec.verify_request("POST", P + "/exchange", body, signed, public_key=signer.public_key(), now=NOW)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b"[]", b'{"unknown":1}', b"\xff"])
def test_control_json_is_an_unambiguous_utf8_object(codec, raw):
    with pytest.raises(codec.MaterialProtocolError):
        codec.parse_control(raw, allowed={"a"}, required={"a"})


async def test_nonce_is_consumed_only_after_scope_and_signature(codec, signer, headers):
    calls = []

    async def authorize(proof):
        calls.append("scope")
        return {"authorized": True}

    async def nonce(key, ttl):
        calls.append((key, ttl))
        return True

    proof, grant = await codec.authenticate(
        "GET", TARGET, b"", headers, public_key=signer.public_key(), now=NOW, authorize=authorize, consume_nonce=nonce
    )
    assert grant["authorized"] and calls[0] == "scope" and calls[1][1] == 120
    assert proof.nonce in calls[1][0]

    async def replay(*_):
        return False

    with pytest.raises(codec.MaterialProtocolError) as error:
        await codec.authenticate(
            "GET",
            TARGET,
            b"",
            headers,
            public_key=signer.public_key(),
            now=NOW,
            authorize=authorize,
            consume_nonce=replay,
        )
    assert error.value.status_code == 409

    async def unavailable(*_):
        raise RuntimeError("secret-store-detail")

    with pytest.raises(codec.MaterialProtocolError) as error:
        await codec.authenticate(
            "GET",
            TARGET,
            b"",
            headers,
            public_key=signer.public_key(),
            now=NOW,
            authorize=authorize,
            consume_nonce=unavailable,
        )
    assert error.value.status_code == 503 and "secret-store-detail" not in str(error.value)


@pytest.mark.parametrize("raw", [b'{"a":1e309}', b'{"a":"\\ud800"}'])
def test_json_overflow_and_unpaired_surrogate_are_refused(codec, raw):
    with pytest.raises(codec.MaterialProtocolError):
        codec.parse_control(raw, allowed={"a"})


def test_header_container_preserves_duplicate_detection(codec, signer, headers):
    import httpx

    raw = httpx.Headers([*headers.items(), ("x-material-key-id", IDENTITY["key_id"])])
    with pytest.raises(codec.MaterialProtocolError):
        codec.verify_request("GET", TARGET, b"", raw, public_key=signer.public_key(), now=NOW)


@pytest.mark.parametrize("value", [True, False, -1, 2**63, "1"])
def test_json_unsigned_integers_are_not_booleans_or_strings(codec, value):
    with pytest.raises(codec.MaterialProtocolError):
        codec.unsigned_integer(value)


def test_material_key_id_database_length_matches_wire(codec, signer):
    from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeMaterialDelegation

    assert RuntimeMaterialDelegation.__table__.c.key_id.type.length == 64
    identity = {**IDENTITY, "key_id": "a" * 64}
    headers = codec.signed_headers("GET", TARGET, b"", private_key=signer, **identity)
    assert codec.verify_request("GET", TARGET, b"", headers, public_key=signer.public_key(), now=NOW).key_id == "a" * 64
