"""Coverage AC: AC-03, AC-35, AC-42. Shared primitive and unchanged SSO trust contract."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from bisheng.sso_sync.domain.services import hmac_auth

SHARED_KEY = "f111-synthetic-shared-key"
PATH = "/api/v1/internal/dsh/content-safety-events"
# Fixed bytes and digests are portable Java/Python protocol vectors.
VECTORS = (
    (b"", "7a58fd350cc7b89e69cc82dbf6aa18194b435018e3a12d7e40b62522815cdcf6"),
    (
        b'{"event_id":"11111111-1111-4111-8111-111111111111"}',
        "b01bceb8c37557d8b1340e1bf9766137ae6100c18e6a128ee63f5b38f9d044d0",
    ),
    (b"\x00first\x00\r\nlast", "c25d41b0ff48f63389b6d2a420a718f913cad7874245701f216a6623e1f07cfb"),
    (
        '{"message":"\u5408\u6210\u5185\u5bb9\U0001f642","value":1}'.encode(),
        "635d754b7c4a617de8700fc986a8323db9f7e39bb4faaed46cfff9e886736946",
    ),
)


@pytest.mark.parametrize("method", ["POST", "post", "PoSt"])
@pytest.mark.parametrize("raw,expected", VECTORS)
def test_shared_primitive_matches_fixed_raw_byte_vectors_and_sso(method, raw, expected):
    from bisheng.common.utils.hmac_signature import compute_hmac_signature

    assert compute_hmac_signature(method, PATH, raw, SHARED_KEY) == expected
    assert hmac_auth.compute_signature(method, PATH, raw, SHARED_KEY) == expected


@pytest.mark.parametrize("transform", [str.lower, str.upper, lambda value: " \t" + value.upper() + "\n"])
def test_signature_comparison_accepts_existing_hex_case_and_header_whitespace(transform):
    from bisheng.common.utils.hmac_signature import compare_hmac_signatures

    expected = VECTORS[1][1]
    assert compare_hmac_signatures(expected, transform(expected)) is True


@pytest.mark.parametrize("provided", [None, "", " ", "0" * 64, "not-hex", "f" * 63, "f" * 65, "\u00e9" * 64])
def test_signature_comparison_rejects_invalid_or_absent_without_exposing_input(provided):
    from bisheng.common.utils.hmac_signature import compare_hmac_signatures

    assert compare_hmac_signatures(VECTORS[1][1], provided) is False


def test_valid_hex_comparison_uses_constant_time_primitive(monkeypatch):
    import bisheng.common.utils.hmac_signature as shared

    calls = []
    compare_digest = shared.hmac.compare_digest

    def observed(expected, provided):
        calls.append((expected, provided))
        return compare_digest(expected, provided)

    monkeypatch.setattr(shared.hmac, "compare_digest", observed)
    assert shared.compare_hmac_signatures(VECTORS[1][1], VECTORS[1][1])
    assert len(calls) == 1


@pytest.mark.parametrize(
    "method,path,body,key",
    [
        ("GET", PATH, VECTORS[1][0], SHARED_KEY),
        ("POST", PATH + "/changed", VECTORS[1][0], SHARED_KEY),
        ("POST", PATH, VECTORS[1][0] + b" ", SHARED_KEY),
        ("POST", PATH, VECTORS[1][0].replace(b"1111", b"2222"), SHARED_KEY),
        ("POST", PATH, VECTORS[1][0], SHARED_KEY + "-changed"),
    ],
)
def test_each_signed_component_is_bound_to_exact_request(method, path, body, key):
    from bisheng.common.utils.hmac_signature import compare_hmac_signatures, compute_hmac_signature

    actual = compute_hmac_signature(method, path, body, key)
    assert not compare_hmac_signatures(VECTORS[1][1], actual)


def make_request(body, *, headers=(), query=b"not-signed=1"):
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {"type": "http", "method": "POST", "path": PATH, "query_string": query, "headers": list(headers)},
        receive=receive,
    )


def configure_sso(monkeypatch, *, secret=SHARED_KEY, header=None):
    monkeypatch.setattr(
        hmac_auth,
        "settings",
        SimpleNamespace(sso_sync=SimpleNamespace(gateway_hmac_secret=secret, signature_header=header)),
    )


async def test_old_sso_default_header_signature_and_body_replay_remain_unchanged(monkeypatch):
    configure_sso(monkeypatch)
    raw, signature = VECTORS[3]
    request = make_request(raw, headers=[(b"x-signature", (" " + signature.upper() + " ").encode())])
    assert await hmac_auth.verify_hmac(request) is None
    assert await request.body() == raw
    assert await request._receive() == {"type": "http.request", "body": raw, "more_body": False}


async def test_old_sso_custom_header_and_empty_query_exclusion_remain_unchanged(monkeypatch):
    configure_sso(monkeypatch, header="X-Synthetic-Signature")
    raw, signature = VECTORS[0]
    request = make_request(raw, headers=[(b"x-synthetic-signature", signature.encode())])
    assert await hmac_auth.verify_hmac(request) is None
    assert await request.body() == b""


@pytest.mark.parametrize("case", ["missing", "empty", "invalid", "tampered", "empty-secret"])
async def test_old_sso_failure_retains_19301_and_never_accepts_empty_shared_key(monkeypatch, case):
    configure_sso(monkeypatch, secret="" if case == "empty-secret" else SHARED_KEY)
    raw, signature = VECTORS[1]
    headers = (
        []
        if case == "missing"
        else [(b"x-signature", (" " if case == "empty" else "0" * 64 if case == "invalid" else signature).encode())]
    )
    request = make_request(raw + b" " if case == "tampered" else raw, headers=headers)
    with pytest.raises(HTTPException) as error:
        await hmac_auth.verify_hmac(request)
    assert error.value.status_code == 19301
    assert SHARED_KEY not in str(error.value.detail)
    assert signature not in str(error.value.detail)
