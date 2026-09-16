"""F052 T104 / T302 — the seeded sample the "same set, whichever door" claims need.

``test/knowledge/test_retrieval_facade_equality.py`` proves the *seam*: two open
faces that build the same identity and pass the same request cannot see
different sets, because below that seam there is one implementation. What it
cannot prove is the **answer** — that OpenFGA, MySQL, Milvus and Elasticsearch
agree on which chunks that identity may read. Proving the answer needs data that
exercises every way a knowledge file can become reachable or unreachable, which
is what this module seeds.

**Four permission sources, deliberately distinct** (the module note at the
bottom of the facade file names them; they are spelled out here because "custom
mode" covers two mechanisms that fail differently):

===== ===================== ===================================================
file  where                 why the subject does / does not reach it
===== ===================== ===================================================
f1    space root, INHERIT   reachable — the space grant flows down untouched
f2    space root, CUSTOM    unreachable — the file answers to its own grant
                            list, and the subject is not on it (an individual
                            revocation of an inherited grant)
f3    folder D1 (CUSTOM)    unreachable — the *folder* detached, so nothing
                            under it inherits the space grant
f4    folder D2 (INHERIT),  unreachable — the authorised path reaches the
      file itself CUSTOM    folder and stops at the file. The case most likely
                            to regress, because every parent check passes
l1    document library L1   reachable — a library-level ``use`` grant, a
                            different resource type with a different action
===== ===================== ===================================================

Plus knowledge space **S2**, granted to nobody, so a request that names it can
be told apart from a request whose grant is merely narrow (26321 rather than a
quietly shorter list).

Everything is seeded for **two subjects with identical grants** — a service
account (SAK) and a natural person (PAT). The pair is the point: F052 AC-42 is
about the natural-person door returning what that person would see in the
platform, and a sample that only ever exercised a service account would leave
the PAT path — a different admission branch — unrun.

Every file carries the same nonce sentence, so one query matches all five and
the visible set is decided by permissions alone rather than by relevance.

Prerequisites (the caller is expected to have checked them; see the suite that
uses this helper):

* a **deployed** BiSheng with MySQL, Redis, OpenFGA, MinIO, Milvus and
  Elasticsearch, **and a running knowledge Celery worker** — without the worker
  the uploaded files never reach Milvus/ES and every set is trivially empty;
* an embedding model configured on at least one existing knowledge base;
* an administrator account, a non-administrator account for the PAT subject,
  and the deployment-level PAT switch available.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

import httpx

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import auth_headers

#: Everything this helper creates is named with it, and cleanup never addresses
#: anything else.
PREFIX = "e2e-f052-retrieval-"

#: ``KnowledgeFileStatus.SUCCESS`` / ``FAILED`` / ``TIMEOUT`` / ``VIOLATION``.
#: Written as literals because the wire is what the helper polls.
FILE_SUCCESS = 2
FILE_TERMINAL_FAILURES = frozenset({3, 6, 7})

#: A freshly uploaded file has to be parsed, embedded and indexed by the
#: knowledge Celery worker before any of it is retrievable.
INGEST_TIMEOUT_SECONDS = float(os.environ.get("F052_E2E_INGEST_TIMEOUT", "300"))
INGEST_POLL_SECONDS = 3.0

#: Level-1 standard model. ``visible`` on a space and ``use`` on a library are
#: both level 1, so one model key covers both resource types.
VIEWER = "viewer"


@dataclass(frozen=True, slots=True)
class SeededFile:
    """One knowledge file plus the reason it is or is not in the expected set."""

    file_id: int
    file_name: str
    reachable: bool
    source: str
    #: ``knowledge_space`` or ``knowledge_library`` — which container it lives
    #: in, so a per-container assertion does not have to guess by position.
    container: str


@dataclass(frozen=True, slots=True)
class RetrievalSample:
    """Everything a set-equality assertion needs, and nothing it has to guess."""

    query: str
    space_id: int
    ungranted_space_id: int
    library_id: int
    folder_ids: tuple[int, ...]
    files: tuple[SeededFile, ...]
    service_account_id: int
    service_account_key: str
    service_account_key_id: str
    natural_person_user_id: int
    natural_person_token: str
    natural_person_jwt: str

    @property
    def reachable_file_ids(self) -> frozenset[int]:
        return frozenset(one.file_id for one in self.files if one.reachable)

    @property
    def unreachable_file_ids(self) -> frozenset[int]:
        return frozenset(one.file_id for one in self.files if not one.reachable)

    @property
    def granted_knowledge_ids(self) -> tuple[int, ...]:
        return (self.space_id, self.library_id)

    @property
    def space_file_ids(self) -> frozenset[int]:
        return frozenset(one.file_id for one in self.files if one.container == "knowledge_space")

    @property
    def library_file_ids(self) -> frozenset[int]:
        return frozenset(one.file_id for one in self.files if one.container == "knowledge_library")

    def describe(self, file_id: int) -> str:
        for one in self.files:
            if one.file_id == file_id:
                return f"{one.file_name} ({one.source})"
        return f"file {file_id} — not part of this sample"


# ---------------------------------------------------------------------------
# Low-level API wrappers (admin JWT unless stated otherwise)
# ---------------------------------------------------------------------------


async def _post(client: httpx.AsyncClient, token: str, path: str, payload: dict) -> dict:
    return assert_resp_200(await client.post(f"{API_BASE}{path}", json=payload, headers=auth_headers(token)))


async def _get(client: httpx.AsyncClient, token: str, path: str, params: dict | None = None) -> dict:
    return assert_resp_200(await client.get(f"{API_BASE}{path}", params=params or {}, headers=auth_headers(token)))


async def _upload(client: httpx.AsyncClient, token: str, name: str, body: bytes) -> str:
    response = await client.post(
        f"{API_BASE}/knowledge/upload",
        files={"file": (name, body, "text/plain")},
        headers=auth_headers(token),
    )
    return assert_resp_200(response)["file_path"]


async def _discover_embedding_model(client: httpx.AsyncClient, token: str) -> str | None:
    """Reuse an embedding model id from an existing document knowledge base.

    Creating a library needs one, and there is no API that lists "the embedding
    models this deployment has configured" without administrator model pages;
    an existing library's ``model`` is the same value and always valid here.
    """

    page = await _get(client, token, "/knowledge", {"type": 0, "page_size": 20})
    for row in page.get("data", []):
        if row.get("model"):
            return str(row["model"])
    return None


# ---------------------------------------------------------------------------
# Permission plumbing
# ---------------------------------------------------------------------------


async def _permission_context(client: httpx.AsyncClient, token: str, resource_type: str, resource_id: int) -> dict:
    return await _get(client, token, f"/permissions/resources/{resource_type}/{resource_id}/context")


async def grant_subject(
    client: httpx.AsyncClient,
    admin_token: str,
    *,
    resource_type: str,
    resource_id: int,
    subject_type: str,
    subject_id: str,
    model_key: str = VIEWER,
) -> dict:
    """Add one grant, through the door that subject type is administered from.

    Service-account grants are refused by the generic resource picker on
    purpose (``mutate_resource_grants`` raises ``ServiceAccountOperationForbidden``),
    so they go through the account detail API instead. Seeding both subjects
    through their real doors is deliberate: a helper that reached into the
    database would seed states the product cannot produce.
    """

    context = await _permission_context(client, admin_token, resource_type, resource_id)
    body = {
        "idempotency_key": f"f052-grant-{uuid4().hex}",
        "expected_resource_version": context["resource_version"],
        "expected_catalog_release_id": context["catalog_release_id"],
        "changes": [{"op": "ADD", "model_key": model_key, "subject": {"type": subject_type, "id": subject_id}}],
    }
    if subject_type == "service_account":
        path = (
            f"/service-accounts/{subject_id}/resource-grants:mutate"
            f"?resource_type={resource_type}&resource_id={resource_id}"
        )
        return await _post(client, admin_token, path, body)
    return await _post(client, admin_token, f"/permissions/resources/{resource_type}/{resource_id}/grants:mutate", body)


async def detach_to_custom_mode(
    client: httpx.AsyncClient,
    admin_token: str,
    *,
    resource_type: str,
    resource_id: int,
) -> None:
    """Switch a resource to CUSTOM so it stops inheriting its parent's grants.

    Two calls, not one: the draft exists so an administrator sees the blast
    radius before confirming, and the apply carries ``confirmed`` for the same
    reason. After the switch the resource keeps only its protected creator
    owner — the administrator — which is exactly the state that makes the
    subjects below unreachable without ever naming them.
    """

    context = await _permission_context(client, admin_token, resource_type, resource_id)
    draft = await _post(
        client,
        admin_token,
        f"/permissions/resources/{resource_type}/{resource_id}/mode-drafts",
        {
            "target_mode": "CUSTOM",
            "expected_resource_version": context["resource_version"],
            "expected_catalog_release_id": context["catalog_release_id"],
        },
    )
    after = await _permission_context(client, admin_token, resource_type, resource_id)
    await _post(
        client,
        admin_token,
        f"/permissions/resources/{resource_type}/{resource_id}/mode-drafts/{draft['draft_id']}/apply",
        {
            "idempotency_key": f"f052-detach-{uuid4().hex}",
            "expected_resource_version": after["resource_version"],
            "expected_catalog_release_id": after["catalog_release_id"],
            "confirmed": True,
        },
    )


async def assert_not_granted(
    client: httpx.AsyncClient,
    admin_token: str,
    *,
    resource_type: str,
    resource_id: int,
    subject_ids: tuple[str, ...],
) -> None:
    """Fail the seeding, not the assertion, when a detachment did not detach.

    A sample that silently kept a grant turns "the set is wrong" into "the
    product is broken", which is the most expensive way to read a red test.
    """

    roster = await _get(
        client,
        admin_token,
        f"/permissions/resources/{resource_type}/{resource_id}/grants",
        {"page_size": 200},
    )
    leaked = [row for row in roster["data"] if str(row["subject"]["id"]) in subject_ids]
    if leaked:
        raise AssertionError(
            f"seeding failed: {resource_type} {resource_id} still grants {leaked} after the CUSTOM-mode detachment"
        )


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


async def _wait_for_space_files(
    client: httpx.AsyncClient,
    admin_token: str,
    space_id: int,
    file_ids: tuple[int, ...],
) -> None:
    deadline = asyncio.get_running_loop().time() + INGEST_TIMEOUT_SECONDS
    while True:
        page = await _get(
            client,
            admin_token,
            f"/knowledge/space/{space_id}/children",
            {"file_ids": list(file_ids), "page_size": 100},
        )
        states = {int(row["id"]): int(row.get("status") or 0) for row in page.get("data", [])}
        failed = {one: state for one, state in states.items() if state in FILE_TERMINAL_FAILURES}
        if failed:
            raise AssertionError(f"seeding failed: space {space_id} files did not parse: {failed}")
        if all(states.get(one) == FILE_SUCCESS for one in file_ids):
            return
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(
                f"seeding timed out after {INGEST_TIMEOUT_SECONDS}s waiting for space {space_id} files {states}; "
                "a knowledge Celery worker has to be running for the sample to become retrievable"
            )
        await asyncio.sleep(INGEST_POLL_SECONDS)


async def _wait_for_library_file(
    client: httpx.AsyncClient,
    admin_token: str,
    library_id: int,
    file_id: int,
) -> None:
    deadline = asyncio.get_running_loop().time() + INGEST_TIMEOUT_SECONDS
    while True:
        page = await _get(
            client,
            admin_token,
            f"/knowledge/file_list/{library_id}",
            {"file_ids": [file_id], "page_size": 50},
        )
        rows = page.get("data") or []
        state = int(rows[0].get("status") or 0) if rows else 0
        if state == FILE_SUCCESS:
            return
        if state in FILE_TERMINAL_FAILURES:
            raise AssertionError(f"seeding failed: library {library_id} file {file_id} ended in status {state}")
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(
                f"seeding timed out after {INGEST_TIMEOUT_SECONDS}s waiting for library file {file_id} (status {state})"
            )
        await asyncio.sleep(INGEST_POLL_SECONDS)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


async def cleanup_prefixed(client: httpx.AsyncClient, admin_token: str) -> None:
    """Remove everything this helper can have left behind, by prefix only.

    Run before seeding as well as after: an interrupted run leaves spaces whose
    names collide, and a collision surfaces as a confusing 18000 rather than as
    "the previous run died".
    """

    spaces = await _get(client, admin_token, "/knowledge", {"type": 3, "name": PREFIX, "page_size": 100})
    for row in spaces.get("data", []):
        if str(row.get("name", "")).startswith(PREFIX):
            await client.delete(f"{API_BASE}/knowledge/space/{row['id']}", headers=auth_headers(admin_token))

    libraries = await _get(client, admin_token, "/knowledge", {"type": 0, "name": PREFIX, "page_size": 100})
    for row in libraries.get("data", []):
        if str(row.get("name", "")).startswith(PREFIX):
            await client.request(
                "DELETE",
                f"{API_BASE}/knowledge/",
                json={"knowledge_id": row["id"]},
                headers=auth_headers(admin_token),
            )

    accounts = await _get(client, admin_token, "/service-accounts", {"keyword": PREFIX, "page": 1, "page_size": 200})
    for row in accounts.get("data", []):
        if str(row.get("name", "")).startswith(PREFIX):
            await client.delete(f"{API_BASE}/service-accounts/{row['id']}", headers=auth_headers(admin_token))


# ---------------------------------------------------------------------------
# The seeding entry point
# ---------------------------------------------------------------------------


@asynccontextmanager
async def seed_retrieval_sample(
    client: httpx.AsyncClient,
    admin_token: str,
    *,
    owner_user_id: int,
    natural_person_user_id: int,
    natural_person_jwt: str,
):
    """Seed the sample, hand it to the caller, and take it down again.

    The natural person is passed in rather than created: issuing a PAT requires
    that person's own session, and a suite that could mint accounts would also
    be able to mint an administrator, which is precisely the account no F052
    assertion may run as (``_identity_shortcut`` allows an administrator every
    action before the action is even validated, so an admin-run green suite
    proves nothing).
    """

    nonce = uuid4().hex[:10]
    query = f"bisheng f052 retrieval sample {nonce}"
    body = (
        f"BiSheng F052 retrieval sample document. {query}. "
        "This sentence exists so one query matches every seeded file and the "
        "returned set is decided by permissions alone."
    ).encode()

    await cleanup_prefixed(client, admin_token)

    model_id = await _discover_embedding_model(client, admin_token)
    if not model_id:
        raise AssertionError(
            "seeding failed: no existing document knowledge base carries an embedding model id, "
            "so the sample's document library cannot be created"
        )

    space = await _post(
        client,
        admin_token,
        "/knowledge/space",
        {"name": f"{PREFIX}s1-{nonce}", "description": "F052 granted space"},
    )
    ungranted = await _post(
        client,
        admin_token,
        "/knowledge/space",
        {"name": f"{PREFIX}s2-{nonce}", "description": "F052 space granted to nobody"},
    )
    library = await _post(
        client,
        admin_token,
        "/knowledge/create",
        {"name": f"{PREFIX}l1-{nonce}", "type": 0, "model": model_id, "description": "F052 granted library"},
    )
    space_id, ungranted_id, library_id = int(space["id"]), int(ungranted["id"]), int(library["id"])

    folder_d1 = await _post(client, admin_token, f"/knowledge/space/{space_id}/folders", {"name": f"d1-{nonce}"})
    folder_d2 = await _post(client, admin_token, f"/knowledge/space/{space_id}/folders", {"name": f"d2-{nonce}"})
    d1_id, d2_id = int(folder_d1["id"]), int(folder_d2["id"])

    async def add_space_file(name: str, parent_id: int | None) -> int:
        path = await _upload(client, admin_token, name, body)
        created = await _post(
            client,
            admin_token,
            f"/knowledge/space/{space_id}/files",
            {"file_path": [path], "parent_id": parent_id},
        )
        rows = created if isinstance(created, list) else created.get("data", [])
        if not rows:
            raise AssertionError(f"seeding failed: {name} was not added to space {space_id}")
        return int(rows[0]["id"])

    f1 = await add_space_file(f"{PREFIX}f1-{nonce}.txt", None)
    f2 = await add_space_file(f"{PREFIX}f2-{nonce}.txt", None)
    f3 = await add_space_file(f"{PREFIX}f3-{nonce}.txt", d1_id)
    f4 = await add_space_file(f"{PREFIX}f4-{nonce}.txt", d2_id)

    library_path = await _upload(client, admin_token, f"{PREFIX}l1-{nonce}.txt", body)
    processed = await _post(
        client,
        admin_token,
        "/knowledge/process",
        {"knowledge_id": library_id, "file_list": [{"file_path": library_path}]},
    )
    library_rows = processed if isinstance(processed, list) else processed.get("data", [])
    if not library_rows:
        raise AssertionError(f"seeding failed: the library file was not accepted by library {library_id}")
    library_file_id = int(library_rows[0]["id"])

    await _wait_for_space_files(client, admin_token, space_id, (f1, f2, f3, f4))
    await _wait_for_library_file(client, admin_token, library_id, library_file_id)

    account = await _post(
        client,
        admin_token,
        "/service-accounts",
        {
            "name": f"{PREFIX}sa1-{nonce}",
            "description": "F052 set-equality subject",
            "resource_owner_user_id": owner_user_id,
        },
    )
    account_id = int(account["id"])
    key = await _post(
        client,
        admin_token,
        f"/service-accounts/{account_id}/keys",
        {"name": f"{PREFIX}key", "scopes": ["knowledge:read"], "delegate_scopes": []},
    )

    subject_ids = (str(account_id), str(natural_person_user_id))
    for resource_type, resource_id in (("knowledge_space", space_id), ("knowledge_library", library_id)):
        await grant_subject(
            client,
            admin_token,
            resource_type=resource_type,
            resource_id=resource_id,
            subject_type="service_account",
            subject_id=str(account_id),
        )
        await grant_subject(
            client,
            admin_token,
            resource_type=resource_type,
            resource_id=resource_id,
            subject_type="user",
            subject_id=str(natural_person_user_id),
        )

    # Order matters: detach only after both subjects hold the space grant, so
    # each detachment removes something that demonstrably reached the file.
    await detach_to_custom_mode(client, admin_token, resource_type="knowledge_file", resource_id=f2)
    await detach_to_custom_mode(client, admin_token, resource_type="folder", resource_id=d1_id)
    await detach_to_custom_mode(client, admin_token, resource_type="knowledge_file", resource_id=f4)
    for resource_type, resource_id in (
        ("knowledge_file", f2),
        ("folder", d1_id),
        ("knowledge_file", f4),
    ):
        await assert_not_granted(
            client,
            admin_token,
            resource_type=resource_type,
            resource_id=resource_id,
            subject_ids=subject_ids,
        )

    # The PAT switch is deployment-level state, so it is read before it is
    # touched and put back exactly as found — a suite that leaves a deployment
    # with personal tokens switched on is a finding of its own.
    pat_settings = await _get(client, admin_token, "/personal-tokens/settings")
    if not pat_settings.get("deployment_enabled"):
        raise AssertionError(
            "seeding failed: this deployment does not offer personal access tokens, "
            "so the natural-person half of the sample cannot be built"
        )
    await client.put(
        f"{API_BASE}/personal-tokens/settings",
        json={"pat_enabled": True, "pat_ttl_days": pat_settings.get("pat_ttl_days") or 30},
        headers=auth_headers(admin_token),
    )
    personal_token = assert_resp_200(
        await client.post(f"{API_BASE}/me/api-token", headers=auth_headers(natural_person_jwt))
    )

    sample = RetrievalSample(
        query=query,
        space_id=space_id,
        ungranted_space_id=ungranted_id,
        library_id=library_id,
        folder_ids=(d1_id, d2_id),
        files=(
            SeededFile(f1, f"f1-{nonce}", True, "inherits the space grant", "knowledge_space"),
            SeededFile(
                f2,
                f"f2-{nonce}",
                False,
                "CUSTOM at the file — the inherited grant was revoked individually",
                "knowledge_space",
            ),
            SeededFile(f3, f"f3-{nonce}", False, "inside folder D1, which detached from the space", "knowledge_space"),
            SeededFile(f4, f"f4-{nonce}", False, "CUSTOM at the file, under an authorised folder", "knowledge_space"),
            SeededFile(library_file_id, f"l1-{nonce}", True, "library-level use grant", "knowledge_library"),
        ),
        service_account_id=account_id,
        service_account_key=key["plaintext"],
        service_account_key_id=str(key["id"]),
        natural_person_user_id=natural_person_user_id,
        natural_person_token=personal_token["plaintext"],
        natural_person_jwt=natural_person_jwt,
    )

    try:
        yield sample
    finally:
        await client.delete(f"{API_BASE}/me/api-token", headers=auth_headers(natural_person_jwt))
        await client.put(
            f"{API_BASE}/personal-tokens/settings",
            json={
                "pat_enabled": pat_settings.get("pat_enabled", False),
                "pat_ttl_days": pat_settings.get("pat_ttl_days") or 30,
            },
            headers=auth_headers(admin_token),
        )
        await cleanup_prefixed(client, admin_token)
