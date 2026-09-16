"""F052 T104 / T302 — the half of "same set, whichever door" that only real stores can answer.

覆盖 AC: AC-05, AC-40, AC-41, AC-42, AC-44

``test/knowledge/test_retrieval_facade_equality.py`` pins the seam — two faces
that build the same identity and pass the same request cannot see different
sets. This file asks the question that seam cannot: **is the set right?** That
is a claim about OpenFGA, MySQL, Milvus and Elasticsearch agreeing over data
seeded through all four permission sources, so it needs the middleware stage.

Everything runs as a **service account and a non-administrator**, never as an
administrator: ``_identity_shortcut`` allows an administrator every action
before the action is even validated, so an admin-run green suite proves nothing
(F048 design K2, and the same rule the F056 square suite is built on).

Prerequisites — a CI middleware stage, or 114:

* ``F052_E2E=1``. The suite creates and deletes ``e2e-f052-retrieval-`` spaces,
  a document library, a service account and one personal access token, and it
  toggles the deployment PAT switch back to whatever it found.
* A **deployed** BiSheng with MySQL, Redis, OpenFGA, MinIO, Milvus and
  Elasticsearch, **plus a running knowledge Celery worker** — without the
  worker nothing the suite uploads ever reaches the indexes and every set is
  trivially empty, which would pass three of these tests for the wrong reason
  (guarded: seeding fails loudly on the ingest timeout).
* ``E2E_API_BASE`` → that deployment's ``/api/v1``; ``E2E_ADMIN_PASSWORD`` if
  the administrator password is not the default.
* ``F052_E2E_OWNER_USER_ID`` — the resource owner recorded on the service
  account.
* ``F052_E2E_USER_ID`` / ``F052_E2E_USER_NAME`` / ``F052_E2E_USER_PASSWORD`` —
  an ordinary account: not a super administrator, not a tenant administrator.
* ``F052_E2E_FGA_DOWN=1`` — set for a **second run** with OpenFGA actually
  stopped; only ``test_with_the_permission_engine_stopped_every_door_errors``
  runs then. It is a separate run because a stopped OpenFGA also makes the
  seeding impossible.
"""

from __future__ import annotations

import asyncio
import os
import time

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers, get_admin_token, get_user_token
from test.e2e.helpers.retrieval_sample import seed_retrieval_sample

API_ORIGIN = API_BASE.removesuffix("/api/v1")
MCP_URL = f"{API_ORIGIN}/api/v2/mcp"

E2E_ENABLED = os.environ.get("F052_E2E") == "1"
FGA_DOWN = os.environ.get("F052_E2E_FGA_DOWN") == "1"

#: F052 26321 — one or more named knowledge bases are not reachable for this
#: identity. The point of the code is that it is *not* a quietly shorter list.
ERR_UNREACHABLE = 26321
#: F052 / F049 — the permission engine could not decide.
PERMISSION_OUTAGE_CODES = frozenset({19002, 19201})

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not E2E_ENABLED,
        reason=(
            "set F052_E2E=1 against a deployment with MySQL + Redis + OpenFGA + MinIO + Milvus/ES "
            "and a running knowledge Celery worker (see this module's docstring)"
        ),
    ),
]


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(f"{name} is required when F052_E2E=1")
    return value


# ---------------------------------------------------------------------------
# The two open doors, as functions of a bearer token
# ---------------------------------------------------------------------------


async def v2_retrieve(
    client: httpx.AsyncClient,
    bearer: str,
    *,
    query: str,
    knowledge_ids: tuple[int, ...],
    top_k: int = 200,
) -> httpx.Response:
    return await client.post(
        f"{API_ORIGIN}/api/v2/filelib/retrieve",
        json={"query": query, "knowledge_base_ids": list(knowledge_ids), "top_k": top_k},
        headers={"Authorization": f"Bearer {bearer}"},
    )


async def mcp_search(bearer: str, *, query: str, knowledge_ids: tuple[int, ...], top_k: int = 200) -> dict:
    """Call the MCP search tool the way a coding agent does — a real client.

    Hand-rolled JSON-RPC posts would keep passing with a broken handshake, and
    "any standard client, zero changes" is the claim under test.
    """

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(MCP_URL, headers={"Authorization": f"Bearer {bearer}"}) as (
        read_stream,
        write_stream,
        _session_id,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(
                "bisheng_knowledge_search",
                {"query": query, "knowledge_ids": list(knowledge_ids), "top_k": top_k},
            )
    return {"isError": bool(result.isError), "content": result.structuredContent, "raw": result}


def _document_ids(chunks: list[dict]) -> frozenset[int]:
    return frozenset(int(chunk["document_id"]) for chunk in chunks)


async def _walk_space_files(client: httpx.AsyncClient, jwt: str, space_id: int) -> set[int]:
    """Every file this person can browse in the space, folders included.

    Recursive rather than a root listing: two of the four permission sources
    live under folders, and a root-only walk would report them absent no matter
    what the permission layer decided.
    """

    found: set[int] = set()
    pending: list[int | None] = [None]
    while pending:
        parent = pending.pop()
        cursor: str | None = None
        for _ in range(50):
            params: dict[str, object] = {"page_size": 100}
            if parent is not None:
                params["parent_id"] = parent
            if cursor:
                params["cursor"] = cursor
            page = assert_resp_200(
                await client.get(
                    f"{API_BASE}/knowledge/space/{space_id}/children",
                    params=params,
                    headers=auth_headers(jwt),
                )
            )
            for row in page.get("data", []):
                if int(row.get("file_type", 1)) == 0:
                    pending.append(int(row["id"]))
                else:
                    found.add(int(row["id"]))
            if not page.get("has_more"):
                break
            cursor = page.get("next_cursor")
    return found


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def client():
    async with httpx.AsyncClient(timeout=60.0) as value:
        yield value


@pytest.fixture(scope="module")
async def admin_token(client: httpx.AsyncClient) -> str:
    return await get_admin_token(client)


@pytest.fixture(scope="module")
async def sample(client: httpx.AsyncClient, admin_token: str):
    if FGA_DOWN:
        pytest.skip("F052_E2E_FGA_DOWN=1 — the outage run cannot seed; run it against an already-seeded deployment")
    user_token = await get_user_token(
        client,
        _required_env("F052_E2E_USER_NAME"),
        _required_env("F052_E2E_USER_PASSWORD"),
    )
    async with seed_retrieval_sample(
        client,
        admin_token,
        owner_user_id=int(_required_env("F052_E2E_OWNER_USER_ID")),
        natural_person_user_id=int(_required_env("F052_E2E_USER_ID")),
        natural_person_jwt=user_token,
    ) as seeded:
        yield seeded


# ---------------------------------------------------------------------------
# AC-40 — the set is what the grants say, no more and no less
# ---------------------------------------------------------------------------


@pytest.mark.skipif(FGA_DOWN, reason="the outage run only exercises AC-44")
async def test_a_service_account_reads_exactly_the_files_it_was_granted(client: httpx.AsyncClient, sample):
    """Every one of the four permission sources decided correctly, in one set.

    Asserting *set equality* rather than "f1 is present" is the whole design:
    an over-disclosure here does not look like a failure, it looks like a
    slightly longer list, and a regression that drops the folder check would
    still return f1.
    """

    response = await v2_retrieve(
        client,
        sample.service_account_key,
        query=sample.query,
        knowledge_ids=sample.granted_knowledge_ids,
    )
    chunks = assert_resp_200(response)["chunks"]
    returned = _document_ids(chunks)

    unexpected = sorted(returned - sample.reachable_file_ids)
    missing = sorted(sample.reachable_file_ids - returned)
    assert not unexpected, "over-disclosed: " + "; ".join(sample.describe(one) for one in unexpected)
    assert not missing, "under-disclosed: " + "; ".join(sample.describe(one) for one in missing)
    assert returned == sample.reachable_file_ids


@pytest.mark.skipif(FGA_DOWN, reason="the outage run only exercises AC-44")
async def test_naming_an_ungranted_space_is_refused_rather_than_quietly_dropped(
    client: httpx.AsyncClient,
    sample,
):
    """26321, not a short list — "narrow grant" and "wrong id" must be tellable apart."""

    response = await v2_retrieve(
        client,
        sample.service_account_key,
        query=sample.query,
        knowledge_ids=(sample.space_id, sample.ungranted_space_id),
    )
    body = assert_resp_error(response, ERR_UNREACHABLE)
    assert str(sample.ungranted_space_id) in str(body.get("data") or body.get("status_message"))


# ---------------------------------------------------------------------------
# AC-41 — one key, two doors, one set (over real stores this time)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(FGA_DOWN, reason="the outage run only exercises AC-44")
async def test_the_mcp_tool_and_v2_return_the_same_chunks_for_the_same_key(client: httpx.AsyncClient, sample):
    """The seam test proves they pass the same call; this proves they get the same answer.

    Compared at chunk granularity — ``(document_id, chunk_index)`` — not merely
    at file granularity: the two faces reach the same facade but shape the
    result separately, and a face that dropped or duplicated chunks of an
    authorised file would still agree on the file set.
    """

    v2 = assert_resp_200(
        await v2_retrieve(
            client,
            sample.service_account_key,
            query=sample.query,
            knowledge_ids=sample.granted_knowledge_ids,
        )
    )
    mcp = await mcp_search(
        sample.service_account_key,
        query=sample.query,
        knowledge_ids=sample.granted_knowledge_ids,
    )
    assert not mcp["isError"], mcp["raw"]

    def keys(chunks: list[dict]) -> set[tuple[int, int]]:
        return {(int(chunk["document_id"]), int(chunk["chunk_index"])) for chunk in chunks}

    assert keys(mcp["content"]["chunks"]) == keys(v2["chunks"])
    assert _document_ids(mcp["content"]["chunks"]) == sample.reachable_file_ids
    assert set(mcp["content"]["effective_scope"]) == set(sample.granted_knowledge_ids)


# ---------------------------------------------------------------------------
# AC-42 — a natural person's key sees that person, not more
# ---------------------------------------------------------------------------


@pytest.mark.skipif(FGA_DOWN, reason="the outage run only exercises AC-44")
async def test_a_personal_token_sees_exactly_what_the_platform_shows_that_person(
    client: httpx.AsyncClient,
    sample,
):
    """The open face and the platform agree about one person, file for file.

    The in-platform comparison is made against the space listing that person
    gets with their own session, not against the space chat: chat retrieval is
    only reachable over SSE and needs a live model, which would make an
    identity assertion depend on a model call. The listing is the same
    permission decision at the same granularity the four sources operate on —
    ``f2``, ``f3`` and ``f4`` have to be absent from **both** sides.
    """

    personal = assert_resp_200(
        await v2_retrieve(
            client,
            sample.natural_person_token,
            query=sample.query,
            knowledge_ids=(sample.space_id,),
        )
    )
    retrieved = _document_ids(personal["chunks"])
    browsed = await _walk_space_files(client, sample.natural_person_jwt, sample.space_id)

    in_this_space = sample.space_file_ids
    assert retrieved == sample.reachable_file_ids & in_this_space
    assert browsed & in_this_space == retrieved
    assert not retrieved & sample.unreachable_file_ids


# ---------------------------------------------------------------------------
# AC-05 — a revoked key stops working, measured against the real Redis cache
# ---------------------------------------------------------------------------


@pytest.mark.skipif(FGA_DOWN, reason="the outage run only exercises AC-44")
async def test_a_revoked_key_stops_working_inside_the_revocation_bound(client: httpx.AsyncClient, admin_token, sample):
    """INV-28's five seconds, timed rather than argued.

    The unit suite proves the credential is re-read on every call and that the
    configured cache TTL is clamped to the bound. Neither can show what the
    deployment's real Redis does with an entry already in flight, which is the
    only thing an administrator revoking a leaked key cares about.
    """

    from bisheng.app_publish.domain.services.app_credential_service import REVOCATION_BOUND_SECONDS

    assert_resp_200(
        await client.post(
            f"{API_BASE}/service-accounts/{sample.service_account_id}/keys/{sample.service_account_key_id}/revoke",
            headers=auth_headers(admin_token),
        )
    )

    started = time.monotonic()
    deadline = started + REVOCATION_BOUND_SECONDS + 2
    refused_after: float | None = None
    while time.monotonic() < deadline:
        response = await v2_retrieve(
            client,
            sample.service_account_key,
            query=sample.query,
            knowledge_ids=(sample.space_id,),
        )
        if response.status_code == 401:
            refused_after = time.monotonic() - started
            break
        await asyncio.sleep(0.5)

    assert refused_after is not None, f"a revoked key still worked {REVOCATION_BOUND_SECONDS + 2}s after revocation"
    assert refused_after <= REVOCATION_BOUND_SECONDS, (
        f"the revoked key kept working for {refused_after:.1f}s, past the {REVOCATION_BOUND_SECONDS}s bound"
    )


# ---------------------------------------------------------------------------
# AC-44 — with the permission engine actually stopped
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not FGA_DOWN,
    reason=(
        "stop OpenFGA on the deployment, then re-run this file alone with F052_E2E_FGA_DOWN=1 "
        "plus F052_E2E_SEEDED_SPACE_ID / F052_E2E_SEEDED_KEY from the seeded run"
    ),
)
async def test_with_the_permission_engine_stopped_every_door_errors_and_returns_nothing(client: httpx.AsyncClient):
    """Fault injection proves this path fails closed; a stopped engine proves the layer below raises.

    The unit suite injects ``PermissionServiceUnavailableError`` at
    ``batch_check_business_actions`` and asserts all four doors re-raise. What
    it cannot check is that a real, stopped OpenFGA produces that error at all,
    rather than timing out into an empty allow-map that every door would then
    treat as a legitimate "you may see nothing".

    Seeding is impossible while the engine is down, so this case takes the ids
    and the key from the seeded run through the environment.
    """

    key = _required_env("F052_E2E_SEEDED_KEY")
    space_id = int(_required_env("F052_E2E_SEEDED_SPACE_ID"))
    query = os.environ.get("F052_E2E_SEEDED_QUERY", "bisheng f052 retrieval sample")

    v2 = await v2_retrieve(client, key, query=query, knowledge_ids=(space_id,))
    body = v2.json()
    assert body["status_code"] in PERMISSION_OUTAGE_CODES, body
    assert not (body.get("data") or {}).get("chunks")

    mcp = await mcp_search(key, query=query, knowledge_ids=(space_id,))
    assert mcp["isError"], mcp["raw"]
    assert not (mcp["content"] or {}).get("chunks")
