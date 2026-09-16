"""Live E2E journey for F057: install the SDK, then exercise auth / retrieve / storage
through a deployed sample application (AC-13, AC-14, AC-15, AC-17, AC-21, AC-24, AC-34).

This is the one test that reads the trio the way a developer meets it — from
outside the container, through ``/apps/{slug}/`` — rather than through mocks.
Everything below therefore needs a real deployment; the module is skipped unless
``F057_E2E=1``.

**What has to have landed before ``F057_E2E=1`` means anything** (the skip reason
repeats this list, because a run that silently proves nothing is worse than a
skip):

1. The SDK wheel is staged in the image — ``GET /api/v1/dev-toolkit/versions``
   answers a non-null ``data.sdk`` section (F057 T029) and
   ``/api/v1/dev-toolkit/simple/bisheng-sdk/`` lists it (T027).
2. ``app_runtime.obo_secret`` is configured **and differs from** ``jwt_secret``.
   Otherwise app-proxy issues no ``X-BiSheng-Access-Token`` (it only warns once,
   ``entry_authz_service.py``), every ``/ask`` answers "visitor credential
   missing", and the journey measures the deployment's configuration rather than
   the SDK. ``test_journey_03b`` fails loudly on exactly that, by design.
3. ``platform-wiring``'s ``example-sdk/`` has been deployed twice — two separate
   applications, both online, both declaring the same knowledge base — and the
   ids are handed to this suite through the environment. Deployment needs an
   approval decision by a human, so it is a **prerequisite of the run**, not a
   step this file performs (deviation from F057 tasks T041 step ②, recorded
   there).
4. Two **non-admin** platform accounts exist with different display names and
   different visible scopes inside the declared knowledge base. ``super_admin``
   short-circuits ReBAC, so an administrator would pass every permission
   assertion here while the permission runtime was broken.
5. The deployment-level personal-token switch is on: the "set equality" case
   compares the app's answer against what the *same user* gets from
   ``POST /api/v2/filelib/retrieve`` and needs that user's own credential.

Still blocked, and therefore **not** covered here (F057 design §6.2):

* the local ``bisheng dev`` half of AC-14 — ``dev`` mints its own ``bsdev.``
  handle that the platform cannot verify, and injects no ``BISHENG_APP_TOKEN``
  (blocker ③), so a local run cannot reach retrieve at all;
* omitting ``knowledge_base_ids`` (contract ③) — ``RetrieveReq`` still requires
  at least one id, so the sample names them explicitly.

Cleanup: this suite creates nothing on the platform except one personal token
per user (revoked in the fixture) and attachments named ``e2e-f057-*`` inside
the two sample applications' own attachment spaces. It never deletes an
application: the sample apps are fixtures of the environment, and their
attachments go with them when an owner deletes them (F054 AC-43).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
import venv
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import auth_headers, get_admin_token, get_user_token

PREFIX = "e2e-f057-"
API_ORIGIN = API_BASE.removesuffix("/api/v1")
E2E_ENABLED = os.environ.get("F057_E2E") == "1"

SKIP_REASON = (
    "set F057_E2E=1 only against a deployment where ALL of these hold: "
    "(1) the SDK wheel is staged — /api/v1/dev-toolkit/versions answers a non-null sdk section; "
    "(2) app_runtime.obo_secret is set and differs from jwt_secret, so app-proxy injects "
    "X-BiSheng-Access-Token; "
    "(3) platform-wiring's example-sdk is deployed as two online applications declaring the same "
    "knowledge base (ids in F057_E2E_APP_ID / F057_E2E_APP_B_ID); "
    "(4) two non-admin accounts with different visible scopes in that knowledge base; "
    "(5) the personal-token switch is enabled deployment-wide"
)

pytestmark = pytest.mark.skipif(not E2E_ENABLED, reason=SKIP_REASON)

# The ten headers app-proxy injects (F054 AC-31 / F057 AC-31). Spelled out here
# rather than imported: ``app_proxy`` is a separate package that is not on the
# backend's path, and this suite runs against a *remote* deployment whose proxy
# may be a different build than the tree it was started from. A drift between
# this list and the source of truth is caught in-repo by the SDK's
# ``test_contract_alignment.py``; here it is the deployment that is under test.
INJECTED_HEADER_NAMES = (
    "x-bisheng-user-id",
    "x-bisheng-user-name",
    "x-bisheng-tenant-id",
    "x-bisheng-dept-id",
    "x-bisheng-dept-name",
    "x-bisheng-dept-path",
    "x-bisheng-subject-kind",
    "x-bisheng-app-id",
    "x-bisheng-access-token",
    "x-bisheng-request-id",
)

# Of the ten, the ones that are always there. The three ``dept-*`` headers are
# **omitted, not emitted empty**, when the visitor has no department
# (``app_proxy/headers.py``: "Absent material is omitted... an app doing
# ``if request.headers.get("X-BiSheng-Dept-Id"):`` must be able to tell 'no
# department' from 'empty department'"). Asserting all ten unconditionally would
# fail on a perfectly healthy deployment whose test accounts sit outside any
# department — which is the common shape after an SSO first login.
ALWAYS_INJECTED_HEADER_NAMES = (
    "x-bisheng-user-id",
    "x-bisheng-user-name",
    "x-bisheng-tenant-id",
    "x-bisheng-subject-kind",
    "x-bisheng-app-id",
    "x-bisheng-access-token",
    "x-bisheng-request-id",
)


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(f"{name} is required when F057_E2E=1")
    return value


def _optional_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"set {name} to run this case")
    return value


def _declared_kb_ids() -> list[int]:
    """The ids the deployed sample passes to ``retrieve.search``.

    Must be the same list as the sample's ``KNOWLEDGE_BASE_IDS`` *and* as its
    manifest's ``capabilities.knowledge_bases`` — the two are one fact, and the
    set-equality case is meaningless if this third copy disagrees with them.
    """
    raw = _required_env("F057_E2E_DECLARED_KB_IDS")
    return [int(piece) for piece in raw.replace(" ", "").split(",") if piece]


@pytest.fixture(scope="module")
async def client():
    # follow_redirects: a bare ``/apps/{slug}`` answers 308 to the trailing-slash
    # form. Without this the journey reads it as a failure and the real cause
    # (a missing slash) never surfaces.
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as value:
        yield value


@pytest.fixture(scope="module")
async def admin_token(client: httpx.AsyncClient) -> str:
    return await get_admin_token(client)


@pytest.fixture(scope="module")
async def user_a_token(client: httpx.AsyncClient) -> str:
    return await get_user_token(
        client,
        _required_env("F057_E2E_USER_A_NAME"),
        _required_env("F057_E2E_USER_A_PASSWORD"),
    )


@pytest.fixture(scope="module")
async def user_b_token(client: httpx.AsyncClient) -> str:
    return await get_user_token(
        client,
        _required_env("F057_E2E_USER_B_NAME"),
        _required_env("F057_E2E_USER_B_PASSWORD"),
    )


@pytest.fixture(scope="module")
async def user_a_pat(client: httpx.AsyncClient, user_a_token: str):
    """User A's own credential for the direct-retrieve half of the comparison.

    A personal token, not the service-account key the app carries: the whole
    point of the comparison is "what this *person* can see", and a service
    account is a different subject with a different visible scope.
    """
    issued = assert_resp_200(await client.post(f"{API_BASE}/me/api-token", headers=auth_headers(user_a_token)))
    try:
        yield issued["plaintext"]
    finally:
        await client.delete(f"{API_BASE}/me/api-token", headers=auth_headers(user_a_token))


@pytest.fixture(scope="module")
async def app_a(client: httpx.AsyncClient, admin_token: str) -> dict:
    return assert_resp_200(
        await client.get(
            f"{API_BASE}/apps/{_required_env('F057_E2E_APP_ID')}",
            headers=auth_headers(admin_token),
        )
    )


@pytest.fixture(scope="module")
async def app_b(client: httpx.AsyncClient, admin_token: str) -> dict:
    return assert_resp_200(
        await client.get(
            f"{API_BASE}/apps/{_required_env('F057_E2E_APP_B_ID')}",
            headers=auth_headers(admin_token),
        )
    )


def _entry(app: dict) -> str:
    """The application's entry address, as the platform composes it (F054 AC-25).

    Read from the detail payload rather than built from the slug: the entry base
    is deployment configuration, and a test that composed it would pass against
    its own assumption instead of the deployment.
    """
    return app["entry_url"].rstrip("/") + "/"


#: How long a stopped application is allowed to keep answering through its entry
#: before the refusal counts as broken. Docker's default stop grace is 10s and
#: the container is torn down inside it, so this is that window plus slack.
STOP_SETTLE_SECONDS = 20.0
STOP_POLL_INTERVAL_SECONDS = 1.0


async def _poll_until_refused(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict,
    **kwargs,
) -> httpx.Response:
    """POST ``url`` until it stops answering 200, or until the window expires.

    Returns the last response either way — the caller asserts on it, so a
    deployment that never settles fails with the real status rather than with a
    timeout error that says nothing about what the entry answered.
    """
    deadline = time.monotonic() + STOP_SETTLE_SECONDS
    response = await client.post(url, headers=headers, **kwargs)
    while response.status_code == 200 and time.monotonic() < deadline:
        await asyncio.sleep(STOP_POLL_INTERVAL_SECONDS)
        response = await client.post(url, headers=headers, **kwargs)
    return response


class TestE2EF057SdkJourney:
    """The install → identity → retrieve → storage journey, end to end."""

    async def test_journey_01_sdk_installs_from_the_platform_index(
        self,
        client: httpx.AsyncClient,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        """AC-34 (install half): pip resolves ``bisheng-sdk`` from the platform itself."""

        versions = assert_resp_200(await client.get(f"{API_BASE}/dev-toolkit/versions"))
        sdk = versions.get("sdk")
        assert sdk is not None, (
            "the deployment ships no SDK wheel — /versions.sdk is null. "
            "Run scripts/pack_sdk_wheel.sh, commit the wheel + manifest, redeploy."
        )

        env_dir: Path = tmp_path_factory.mktemp("f057-sdk-venv")
        venv.create(env_dir, with_pip=True)
        python = env_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        index_url = f"{API_ORIGIN}{sdk['index_path']}"
        completed = subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--extra-index-url",
                index_url,
                "--trusted-host",
                httpx.URL(API_ORIGIN).host,
                "bisheng-sdk",
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        assert completed.returncode == 0, completed.stderr[-2000:]

        printed = subprocess.run(
            [str(python), "-c", "import bisheng_sdk; print(bisheng_sdk.__version__)"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert printed.returncode == 0, printed.stderr[-2000:]
        assert printed.stdout.strip() == sdk["version"]

    async def test_journey_02_both_samples_are_online(self, app_a: dict, app_b: dict) -> None:
        """Prerequisite made explicit: a stopped sample fails everything below for the wrong reason."""

        assert app_a["state"] == "online", f"app A is {app_a['state']}, not online"
        assert app_b["state"] == "online", f"app B is {app_b['state']}, not online"
        assert app_a["app_id"] != app_b["app_id"], "app A and app B must be two separate applications"

    async def test_journey_03_each_visitor_gets_their_own_identity(
        self,
        client: httpx.AsyncClient,
        app_a: dict,
        user_a_token: str,
        user_b_token: str,
    ) -> None:
        """AC-34: the same code, one deployment, two visitors — each sees themselves."""

        entry = _entry(app_a)
        name_a = _required_env("F057_E2E_USER_A_DISPLAY_NAME")
        name_b = _required_env("F057_E2E_USER_B_DISPLAY_NAME")

        page_a = await client.get(entry, headers=auth_headers(user_a_token))
        page_b = await client.get(entry, headers=auth_headers(user_b_token))
        assert page_a.status_code == 200, page_a.text[:300]
        assert page_b.status_code == 200, page_b.text[:300]
        assert name_a in page_a.text and name_b not in page_a.text
        assert name_b in page_b.text and name_a not in page_b.text

    async def test_journey_03b_the_ten_headers_arrive_including_the_access_token(
        self,
        client: httpx.AsyncClient,
        app_a: dict,
        user_a_token: str,
    ) -> None:
        """AC-31: nothing outside the ten arrives, the seven unconditional ones do.

        The access-token assertion is the one that catches a deployment whose
        ``app_runtime.obo_secret`` is missing or equal to ``jwt_secret``: the
        platform only warns once about that, and every retrieve below would then
        fail as "visitor credential missing" — a configuration fault wearing an
        SDK fault's clothes. It is checked **first** so that failure names the
        configuration instead of surfacing as a set difference.
        """

        response = await client.get(f"{_entry(app_a)}__whoami", headers=auth_headers(user_a_token))
        assert response.status_code == 200, response.text[:300]
        injected = {key.lower() for key in response.json()}

        assert response.json().get("x-bisheng-access-token"), (
            "no visitor credential injected — set app_runtime.obo_secret to a value "
            "different from jwt_secret and restart the backend"
        )
        # Nothing outside the contract leaks into the app's namespace...
        assert injected <= set(INJECTED_HEADER_NAMES), sorted(injected - set(INJECTED_HEADER_NAMES))
        # ...and everything that does not depend on the visitor's department is there.
        assert set(ALWAYS_INJECTED_HEADER_NAMES) <= injected, sorted(set(ALWAYS_INJECTED_HEADER_NAMES) - injected)

    async def test_journey_04_health_probe_needs_no_identity(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
        app_a: dict,
        user_a_token: str,
    ) -> None:
        """AC-34: ``/healthz`` reads no identity — the platform's own probe carries none.

        Two halves, because neither alone is the claim: through the entry the
        endpoint answers 200 without the app reading identity, and the platform's
        headerless probe — the one that actually runs without a session — reports
        the instance healthy.
        """

        healthz = await client.get(f"{_entry(app_a)}healthz", headers=auth_headers(user_a_token))
        assert healthz.status_code == 200, healthz.text[:300]
        assert healthz.json().get("status") == "ok"

        instance = assert_resp_200(
            await client.get(
                f"{API_BASE}/apps/{app_a['app_id']}/instance",
                headers=auth_headers(admin_token),
            )
        )
        assert instance.get("health") == "healthy", instance

    async def test_journey_05_ask_equals_the_same_users_own_retrieve(
        self,
        client: httpx.AsyncClient,
        app_a: dict,
        user_a_token: str,
        user_a_pat: str,
    ) -> None:
        """AC-13: set equality between the app's answer and the user's own retrieve.

        Same person, same query, same declared knowledge bases, same ``top_k``.
        Not "roughly the same number of chunks": AC-13 says neither more nor
        less, and a subset is exactly what a broken whitelist intersection looks
        like.
        """

        query = _required_env("F057_E2E_QUERY")
        top_k = 5  # the sample's own top_k; the direct call must match it

        through_app = await client.post(
            f"{_entry(app_a)}ask",
            params={"q": query},
            headers=auth_headers(user_a_token),
        )
        assert through_app.status_code == 200, through_app.text[:500]
        app_chunks = {(chunk["document"], chunk["index"], chunk["content"]) for chunk in through_app.json()["chunks"]}

        direct = await client.post(
            f"{API_ORIGIN}/api/v2/filelib/retrieve",
            json={
                "query": query,
                "knowledge_base_ids": _declared_kb_ids(),
                "top_k": top_k,
            },
            headers={"Authorization": f"Bearer {user_a_pat}"},
        )
        own_chunks = {
            (chunk["document_name"], chunk["chunk_index"], chunk["content"])
            for chunk in assert_resp_200(direct)["chunks"]
        }

        assert app_chunks, "the query returned nothing through the app — pick a query that matches"
        assert app_chunks == own_chunks

    async def test_journey_05b_a_library_the_user_cannot_see_does_not_appear(
        self,
        client: httpx.AsyncClient,
        app_a: dict,
        user_b_token: str,
    ) -> None:
        """AC-13: declared by the app, invisible to this user — the chunks stay out.

        Needs a second account whose visible scope inside the declared knowledge
        base is a strict subset of user A's, plus the name of a document only
        user A can see.
        """

        query = _required_env("F057_E2E_QUERY")
        forbidden_document = _optional_env("F057_E2E_DOCUMENT_ONLY_A_CAN_SEE")

        response = await client.post(
            f"{_entry(app_a)}ask",
            params={"q": query},
            headers=auth_headers(user_b_token),
        )
        assert response.status_code == 200, response.text[:500]
        documents = {chunk["document"] for chunk in response.json()["chunks"]}
        assert forbidden_document not in documents, documents

    async def test_journey_06_an_undeclared_library_is_refused(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
        user_a_token: str,
    ) -> None:
        """AC-17: asking for a library outside the declaration fails the whole request.

        Needs a third deployment of the sample whose ``KNOWLEDGE_BASE_IDS``
        names a library its manifest does not declare — the sample cannot be
        told to do that at call time, and inventing a query parameter for it
        would be testing a test-only code path.
        """

        app_id = _optional_env("F057_E2E_UNDECLARED_APP_ID")
        app = assert_resp_200(await client.get(f"{API_BASE}/apps/{app_id}", headers=auth_headers(admin_token)))

        response = await client.post(
            f"{_entry(app)}ask",
            params={"q": _required_env("F057_E2E_QUERY")},
            headers=auth_headers(user_a_token),
        )
        # The sample maps TargetUnreachableError to 400 and
        # CapabilityNotDeclaredError to 403 (both are "your declaration, not
        # your query"); what must never happen is a 200 with fewer chunks.
        assert response.status_code in {400, 403}, response.text[:500]
        assert "next_step" in response.json()

    async def test_journey_07_attachments_do_not_cross_applications(
        self,
        client: httpx.AsyncClient,
        app_a: dict,
        app_b: dict,
        user_a_token: str,
    ) -> None:
        """AC-21 / AC-24: application B cannot see what the same person stored in A."""

        filename = f"{PREFIX}{uuid4().hex[:8]}.txt"
        uploaded = await client.post(
            f"{_entry(app_a)}upload",
            files={"file": (filename, b"f057 journey attachment", "text/plain")},
            headers=auth_headers(user_a_token),
        )
        assert uploaded.status_code == 200, uploaded.text[:500]
        stored_path = uploaded.json()["path"]
        assert stored_path.endswith(filename)

        in_a = await client.get(f"{_entry(app_a)}files", headers=auth_headers(user_a_token))
        assert in_a.status_code == 200, in_a.text[:500]
        assert stored_path in {row["path"] for row in in_a.json()}

        in_b = await client.get(f"{_entry(app_b)}files", headers=auth_headers(user_a_token))
        assert in_b.status_code == 200, in_b.text[:500]
        assert stored_path not in {row["path"] for row in in_b.json()}

    async def test_journey_07b_one_visitor_cannot_read_anothers_attachment(
        self,
        client: httpx.AsyncClient,
        app_a: dict,
        user_a_token: str,
        user_b_token: str,
    ) -> None:
        """The per-person half is the application's own (the sample checks the prefix).

        Kept in the journey because it is the half developers get wrong: the
        platform isolates by application, never by person.
        """

        filename = f"{PREFIX}{uuid4().hex[:8]}.txt"
        uploaded = await client.post(
            f"{_entry(app_a)}upload",
            files={"file": (filename, b"belongs to user A", "text/plain")},
            headers=auth_headers(user_a_token),
        )
        assert uploaded.status_code == 200, uploaded.text[:500]
        path = uploaded.json()["path"]

        as_b = await client.get(f"{_entry(app_a)}files/{path}", headers=auth_headers(user_b_token))
        assert as_b.status_code == 403, as_b.text[:300]

        listed_by_b = await client.get(f"{_entry(app_a)}files", headers=auth_headers(user_b_token))
        assert listed_by_b.status_code == 200, listed_by_b.text[:300]
        assert path not in {row["path"] for row in listed_by_b.json()}

    async def test_journey_08_an_offline_application_refuses_instead_of_answering(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
        app_b: dict,
        user_a_token: str,
    ) -> None:
        """AC-25's platform half: once B is stopped, its entry refuses — it does not answer.

        The in-process half of AC-25 — retrieve and storage raising *different*
        errors while the process is still alive after the application went
        offline — cannot be observed from out here: stopping the application
        takes the container with it. That half is covered by the SDK's own unit
        tests (``src/bisheng-sdk/tests/``), which drive the refusal envelopes
        directly.
        """

        entry = _entry(app_b)
        assert_resp_200(
            await client.post(f"{API_BASE}/apps/{app_b['app_id']}/actions/stop", headers=auth_headers(admin_token))
        )
        try:
            for path, kwargs in (
                ("ask", {"params": {"q": "anything"}}),
                ("upload", {"files": {"file": (f"{PREFIX}offline.txt", b"x", "text/plain")}}),
            ):
                # Retried, not probed once: the state row flips inside the stop
                # call, but the container still gets docker's stop grace period
                # (~10s) and a request that slips in during it is answered by a
                # process that is on its way out. Reading that single 200 as
                # "the platform kept serving a stopped application" would be a
                # false alarm; refusing to settle within the window is the real
                # defect, and that is what this asserts.
                response = await _poll_until_refused(
                    client,
                    f"{entry}{path}",
                    headers=auth_headers(user_a_token),
                    **kwargs,
                )
                assert response.status_code != 200, (
                    f"{path} still answered 200 {STOP_SETTLE_SECONDS}s after the application was stopped"
                )
                assert "Traceback" not in response.text
        finally:
            assert_resp_200(
                await client.post(
                    f"{API_BASE}/apps/{app_b['app_id']}/actions/resume",
                    headers=auth_headers(admin_token),
                )
            )
