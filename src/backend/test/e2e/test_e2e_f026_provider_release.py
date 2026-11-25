"""Read-only T056 live probes. See the feature's e2e-checklist.md before opting in.

Both providers, both people and both citations belong to ONE disposable tenant.
Do not discover targets, mint credentials, provision data, or follow signed URLs.
"""

import os
import re
from contextlib import ExitStack
from dataclasses import dataclass

import httpx
import pytest

from test.e2e.helpers.auth import auth_headers

PREFIX = "F026_E2E_"
PROVIDERS = ("native", "weknora")
MARKER = {"native": "N026", "weknora": "S026"}
pytestmark = pytest.mark.e2e


def require(ok, message):
    # Do not let pytest introspection show a token, signed locator, or a chunk.
    if not ok:
        pytest.fail(message, pytrace=False)


def setting(key, pattern):
    value = os.environ.get(PREFIX + key, "")
    require(re.fullmatch(pattern, value) is not None, f"Missing or invalid {PREFIX}{key}")
    return value


def number(key):
    return int(setting(key, r"[1-9][0-9]{0,17}"))


@dataclass(frozen=True, repr=False)
class Sample:
    space: int
    file: int
    citation: str


@dataclass(repr=False)
class Live:
    clients: dict
    samples: dict
    anchor: tuple


def fixture_request(client, path, *, body=None):
    try:
        return client.get(path) if body is None else client.post(path, json=body)
    except httpx.HTTPError:
        pytest.fail("Fixture API transport failed (details withheld)", pytrace=False)


def envelope(response, code=200):
    require(response.status_code == 200 and not response.is_redirect, "Unexpected fixture API HTTP status")
    try:
        result = response.json()
    except (ValueError, UnicodeError):
        pytest.fail("Expected fixture API JSON (body withheld)", pytrace=False)
    require(
        isinstance(result, dict) and set(result) >= {"status_code", "status_message", "data"}, "Invalid API envelope"
    )
    require(result["status_code"] == code, f"Expected fixture business code {code}")
    require(isinstance(result["status_message"], str) and bool(result["status_message"]), "Missing status message")
    if code == 200:
        require(result["status_message"] == "SUCCESS", "Unexpected fixture success envelope")
    require(isinstance(result["data"], dict), "Invalid fixture data shape")
    return result["data"]


@pytest.fixture(scope="module")
def live():
    opt_in = os.environ.get(PREFIX + "RUN")
    if opt_in is None:
        pytest.skip("Not run: explicitly configured isolated F026 deployment required")
    require(opt_in == "owned-isolated-test", "Refusing target: F026_E2E_RUN must attest owned isolated test fixtures")
    # No global API_BASE fallback, embedded credentials, query string, or redirect targets.
    base = setting("API_BASE", r"https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?(?:/[A-Za-z0-9_-]+)*/api/v1")
    tenant = number("TENANT_ID")
    require(tenant != 1, "Refusing root tenant")
    ids = {role: number(f"{role}_ID") for role in ("READER", "LIMITED")}
    require(1 not in ids.values() and len(set(ids.values())) == 2, "Expected two distinct ordinary fixture people")
    tokens = {role: setting(f"{role}_TOKEN", r"[A-Za-z0-9_.-]+") for role in ids}
    require(tokens["READER"] != tokens["LIMITED"], "Expected different fixture credentials")
    samples = {
        key: Sample(
            number(f"{key.upper()}_SPACE_ID"),
            number(f"{key.upper()}_FILE_ID"),
            setting(f"{key.upper()}_CITATION_ID", r"knowledgesearch_[a-f0-9]{8}"),
        )
        for key in PROVIDERS
    }
    n, w = (samples[key] for key in PROVIDERS)
    require(n.space != w.space and n.file != w.file and n.citation != w.citation, "Fixture resources must be distinct")
    anchor = tuple(number(f"WEKNORA_{key}") for key in ("VERSION_ID", "GENERATION", "EPOCH"))

    # All local fixture facts must exist BEFORE even a whoami request.
    with ExitStack() as stack:
        clients = {}
        for role, user_id in ids.items():
            clients[role] = client = stack.enter_context(
                httpx.Client(
                    base_url=base + "/",
                    headers=auth_headers(tokens[role]),
                    timeout=45.0,
                    trust_env=False,
                    follow_redirects=False,
                )
            )
            who = envelope(fixture_request(client, "user/info"))
            require(
                who.get("user_id") == user_id and who.get("leaf_tenant_id") == tenant,
                "Fixture subject or tenant mismatch; no resource request made",
            )
            require(
                str(who.get("user_name", "")).startswith("e2e-f026-")
                and str(who.get("leaf_tenant_name", "")).startswith("e2e-f026-"),
                "Not a dedicated F026 tenant/person",
            )
            require(
                who.get("role") not in (None, "", "admin")
                and not who.get("admin_groups")
                and all(
                    who.get(flag) is False
                    for flag in ("is_global_super", "is_department_admin", "is_child_admin", "can_manage_user_groups")
                ),
                "Elevated or unverified test identity",
            )
        yield Live(clients, samples, anchor)


@pytest.fixture(params=PROVIDERS, ids=PROVIDERS)
def provider(live, request):
    # A broken W binding must not prevent the Native control from running.
    key = request.param
    sample = live.samples[key]
    for client in live.clients.values():
        caps = envelope(fixture_request(client, f"knowledge/space/{sample.space}/capabilities"))
        require(caps.get("provider_key") == key, f"Expected visible {key} space")
        if key == "weknora":
            require(caps.get("generation") == live.anchor[1], "WeKnora generation drift")
    return key


def test_fixture_retrieval(live, provider):
    """AC-01/26/32: actual Work retrieval, not just a provider capability flag."""
    sample = live.samples[provider]
    query = {"space_ids": [sample.space], "query": MARKER[provider]}
    for role in ("READER", "LIMITED"):
        chunks = envelope(fixture_request(live.clients[role], "knowledge/space/retrieve", body=query)).get("chunks")
        require(isinstance(chunks, list), "Missing retrieval result array")
        if role == "LIMITED":
            require(not chunks, "File-ineligible viewer received a hit in the single-file fixture space")
            continue
        require(
            bool(chunks)
            and all(
                isinstance(c, dict)
                and c.get("space_id") == sample.space
                and str(c.get("document_id")) == str(sample.file)
                and isinstance(c.get("content"), str)
                for c in chunks
            ),
            f"Expected only the known {provider} fixture file",
        )
        other = MARKER["native" if provider == "weknora" else "weknora"]
        require(
            any(MARKER[provider] in c["content"] for c in chunks) and all(other not in c["content"] for c in chunks),
            f"Expected the isolated {provider} fixture marker, not empty or mixed results",
        )


def test_fixture_citation_click(live, provider):
    """AC-13/28: resolve the same stored citation as two viewers; actually open W's controlled excerpt."""
    sample = live.samples[provider]
    reader, limited = live.clients["READER"], live.clients["LIMITED"]
    item = envelope(fixture_request(reader, f"citations/{sample.citation}"))
    require(
        (item.get("citationId"), item.get("accessScope"), item.get("type")) == (sample.citation, "per_user", "rag"),
        "Unexpected citation identity/scope/type",
    )
    payload = item.get("sourcePayload")
    require(
        isinstance(payload, dict)
        and (payload.get("knowledgeId"), payload.get("documentId")) == (sample.space, sample.file),
        "Citation points outside its fixture",
    )
    denied = envelope(fixture_request(limited, f"citations/{sample.citation}"), 404)
    require(
        denied.get("reason") == "forbidden" and set(denied) <= {"reason", "exception"},
        "Expected viewer denial, not source expiry",
    )
    if provider == "native":
        # Native retains its signing contract. Do not send a BiSheng cookie to an object store.
        require(
            bool(payload.get("previewUrl") or payload.get("downloadUrl")) and payload.get("generation") is None,
            "Expected the authorized Native source locator",
        )
        return
    version, generation, epoch = live.anchor
    require(
        tuple(payload.get(k) for k in ("versionId", "generation", "operationEpoch")) == live.anchor,
        "Citation does not identify the registered WeKnora revision",
    )
    path = f"knowledge/space/{sample.space}/files/{sample.file}/content/"
    suffix = f"?version_id={version}&generation={generation}&epoch={epoch}"
    preview = f"{path}preview{suffix}"
    require(
        payload.get("previewUrl") == "/api/v1/" + preview
        and not payload.get("sourceUrl")
        and payload.get("downloadUrl") in (None, "", f"/api/v1/{path}download{suffix}"),
        "Non-controlled or stale source locator",
    )
    # Request our canonical path ONLY after equality with the returned locator.
    opened = fixture_request(reader, preview)
    require(
        opened.status_code == 200
        and opened.headers.get("content-type", "").split(";")[0] == "text/plain"
        and "no-store" in opened.headers.get("cache-control", "")
        and MARKER[provider].encode() in opened.content,
        "Controlled preview did not return the registered private text excerpt",
    )
    rejected = envelope(fixture_request(limited, preview), 19000)
    require(
        set(rejected) == {"exception"} and rejected["exception"] == "Permission denied",
        "Expected denial without file bytes",
    )
