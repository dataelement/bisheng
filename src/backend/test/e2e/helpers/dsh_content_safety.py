"""Explicit live HTTP fixtures; never initialize application state or forge identity.

Coverage AC: AC-01, AC-02, AC-03, AC-04, AC-10, AC-11, AC-12, AC-13, AC-37, AC-45.
"""

import asyncio
import copy
import json
import os
import re
import stat
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from test.e2e.helpers.auth import auth_headers
from test.e2e.helpers.dsh import native_desktop_session


class LiveSafetyError(AssertionError):
    """Fixed, credential-free live fixture failure."""


class Secret(str):
    def __repr__(self) -> str:
        return "<redacted>"


def _private_file(path: str) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid():
                raise LiveSafetyError("Live credential file must be owned by this user with mode 0600")
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                value = handle.read(16385)
            if not value or len(value) > 16384:
                raise LiveSafetyError("Live credential file has an invalid size")
            return value
        finally:
            os.close(descriptor)
    except OSError:
        raise LiveSafetyError("Live credential file is unavailable or unsafe") from None


def _url(value: str, *, origin: bool = False, loopback: bool = False) -> str:
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme in {"http", "https"} and parsed.hostname and parsed.port != 0
        valid = valid and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
        valid = valid and (not origin or not parsed.path)
        valid = valid and (not loopback or parsed.hostname in {"127.0.0.1", "::1", "localhost"})
        if not valid or value != value.strip() or value.endswith("/"):
            raise ValueError
    except ValueError:
        raise LiveSafetyError("Live endpoint must be an explicit, credential-free URL") from None
    return value


def _positive(value: str, name: str) -> int:
    if not value.isascii() or not value.isdecimal() or not 0 < int(value) <= 9_223_372_036_854_775_807:
        raise LiveSafetyError(f"Invalid positive live parameter: {name}")
    return int(value)


@dataclass(frozen=True, repr=False)
class LiveSafetySettings:
    api_base: str
    platform_origin: str
    provider_control_url: str
    platform_token: Secret
    provider_key: Secret
    run_id: str
    chat_model_id: int | None = None
    responses_model_id: int | None = None
    allow_policy_mutation: bool = False

    def __repr__(self) -> str:
        return "LiveSafetySettings(<redacted>)"

    @property
    def prefix(self) -> str:
        return f"e2e-f111-live-{self.run_id}-"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *, require_models: bool = True):
        values = os.environ if env is None else env
        if values.get("DSH_SAFETY_E2E") != "1":
            raise LiveSafetyError("Live safety E2E requires explicit DSH_SAFETY_E2E=1")
        required = (
            "E2E_API_BASE",
            "DSH_E2E_PLATFORM_ORIGIN",
            "DSH_E2E_SESSION_FILE",
            "DSH_E2E_PROVIDER_CONTROL_URL",
            "DSH_E2E_PROVIDER_KEY_FILE",
            "DSH_E2E_RUN_ID",
        )
        if any(not values.get(name) for name in required):
            raise LiveSafetyError(
                "Live safety E2E is missing required endpoints, session, provider key or run identifier"
            )
        api_base = _url(values["E2E_API_BASE"])
        if not api_base.endswith("/api/v1"):
            raise LiveSafetyError("Live API base must end in /api/v1")
        origin = _url(values["DSH_E2E_PLATFORM_ORIGIN"], origin=True)
        control = _url(values["DSH_E2E_PROVIDER_CONTROL_URL"], loopback=True)
        try:
            session = json.loads(_private_file(values["DSH_E2E_SESSION_FILE"]))
        except (ValueError, UnicodeError):
            raise LiveSafetyError("Live session file is not valid JSON") from None
        if not isinstance(session, dict) or any(key in session for key in ("password", "secret_key")):
            raise LiveSafetyError("Live session file must contain only issued session data")
        if session.get("api_base") != api_base or session.get("platform_origin", session.get("origin")) != origin:
            raise LiveSafetyError("Live session does not identify the selected deployment")
        for key, expected in (("api_base", api_base), ("origin", origin), ("platform_origin", origin)):
            if key in session and session[key] != expected:
                raise LiveSafetyError("Live session endpoint does not match the selected deployment")
        token = session.get("access_token")
        if not isinstance(token, str) or not token or any(char.isspace() for char in token):
            raise LiveSafetyError("Live session lacks an issued platform token")
        try:
            key = _private_file(values["DSH_E2E_PROVIDER_KEY_FILE"]).decode("ascii").strip()
        except UnicodeError:
            raise LiveSafetyError("Test provider key must be ASCII") from None
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", key):
            raise LiveSafetyError("Test provider key must be a bounded random test value")
        run_id = values["DSH_E2E_RUN_ID"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{7,47}", run_id):
            raise LiveSafetyError("Live run identifier must be a bounded unique lowercase label")
        models = []
        for name in ("DSH_E2E_CHAT_MODEL_ID", "DSH_E2E_RESPONSES_MODEL_ID"):
            value = values.get(name)
            if require_models and not value:
                raise LiveSafetyError("Live safety E2E requires explicit test model identifiers")
            models.append(_positive(value, name) if value else None)
        return cls(
            api_base,
            origin,
            control,
            Secret(token),
            Secret(key),
            run_id,
            *models,
            values.get("DSH_E2E_ALLOW_POLICY_MUTATION") == "1",
        )


def checked_json(response: httpx.Response, *, unified: bool = True) -> dict | list:
    """Keep diagnostic bodies and credentials out of assertion exceptions."""
    if response.status_code != 200:
        raise LiveSafetyError(f"Live HTTP operation failed: HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        raise LiveSafetyError("Live HTTP operation returned invalid JSON") from None
    if not isinstance(body, dict):
        raise LiveSafetyError("Live HTTP operation returned an invalid object")
    if unified:
        if body.get("status_code", body.get("statusCode")) != 200:
            raise LiveSafetyError("Live HTTP operation returned a business failure")
        body = body.get("data")
    if not isinstance(body, (dict, list)):
        raise LiveSafetyError("Live HTTP operation returned invalid data")
    return body


@dataclass(frozen=True)
class OwnedResource:
    kind: str
    identifier: str
    name: str


@dataclass
class OwnedResources:
    prefix: str
    resources: dict[tuple[str, str], OwnedResource] = field(default_factory=dict)

    def __post_init__(self):
        if not re.fullmatch(r"e2e-f111-live-[a-z0-9][a-z0-9-]{7,47}-", self.prefix):
            raise LiveSafetyError("Owned resources require this live suite prefix")

    def register(self, kind: str, identifier: str | int, name: str) -> OwnedResource:
        if (
            kind not in {"model", "server", "user", "department", "scenario"}
            or not isinstance(name, str)
            or not name.startswith(self.prefix)
            or len(self.prefix) < 16
        ):
            raise LiveSafetyError("Refusing to register a resource outside this test run")
        value = str(identifier)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
            raise LiveSafetyError("Invalid owned resource identifier")
        resource = OwnedResource(kind, value, name)
        previous = self.resources.setdefault((kind, value), resource)
        if previous != resource:
            raise LiveSafetyError("Owned resource registration conflicts")
        return resource

    def require(self, kind: str, identifier: str | int, observed_name: str) -> OwnedResource:
        resource = self.resources.get((kind, str(identifier)))
        if (
            resource is None
            or not isinstance(observed_name, str)
            or resource.name != observed_name
            or not observed_name.startswith(self.prefix)
        ):
            raise LiveSafetyError("Refusing to mutate a resource not verified as test-owned")
        return resource


class LiveSafetyHTTP:
    """Separate browser cookies, native credentials and private provider control."""

    def __init__(self, settings: LiveSafetySettings):
        self.settings = settings
        self.owned = OwnedResources(settings.prefix)
        self.admin = httpx.AsyncClient(
            timeout=90,
            trust_env=False,
            follow_redirects=False,
            headers={**auth_headers(settings.platform_token), "Origin": settings.platform_origin},
        )
        self.native = httpx.AsyncClient(timeout=90, trust_env=False, follow_redirects=False)
        self.control = httpx.AsyncClient(
            timeout=10,
            trust_env=False,
            follow_redirects=False,
            headers={"Authorization": f"Bearer {settings.provider_key}"},
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.admin.aclose()
        await self.native.aclose()
        await self.control.aclose()

    async def desktop_session(self, platform_token: str | None = None) -> dict:
        async with httpx.AsyncClient(timeout=90, trust_env=False, follow_redirects=False) as exchange:
            credentials = await native_desktop_session(
                exchange,
                platform_token or self.settings.platform_token,
                self.settings.prefix,
                api_base=self.settings.api_base,
                platform_origin=self.settings.platform_origin,
            )
            return {
                key: Secret(value) if key in {"access_token", "refresh_token"} else value
                for key, value in credentials.items()
            }

    async def model_creation_defaults(self) -> dict:
        """Fail before model creation if automatic default filling could affect other users."""
        snapshots = {}
        for name in ("knowledge", "assistant", "evaluation", "workbench/settings"):
            envelope = checked_json(await self.admin.get(f"{self.settings.api_base}/llm/{name}"))
            if not isinstance(envelope, dict) or not isinstance(envelope.get("data"), dict):
                raise LiveSafetyError("Model defaults returned an invalid settings envelope")
            snapshots[name] = envelope["data"]
        knowledge = snapshots["knowledge"]
        assistant = snapshots["assistant"]
        required = (
            knowledge.get("source_model_id"),
            knowledge.get("extract_title_model_id"),
            knowledge.get("qa_similar_model_id"),
            snapshots["evaluation"].get("model_id"),
            assistant.get("auto_llm"),
            assistant.get("llm_list"),
            snapshots["workbench/settings"].get("chat_title_llm"),
        )
        if not all(required):
            raise LiveSafetyError("Model creation could populate empty global defaults; dedicated setup is required")
        return copy.deepcopy(snapshots)

    async def provider_scenario(self, identifier: str, **scenario) -> dict:
        self.owned.register("scenario", identifier, identifier)
        body = checked_json(
            await self.control.post(
                f"{self.settings.provider_control_url}/__control/scenarios", json={"id": identifier, **scenario}
            ),
            unified=False,
        )
        await self.provider_counts(identifier)
        return body

    async def provider_totals(self) -> dict:
        """Read physical model-path arrivals, including rejected or unmarked requests."""
        value = checked_json(
            await self.control.get(f"{self.settings.provider_control_url}/__control/counters"), unified=False
        )
        fields = {
            "model_posts",
            "chat_posts",
            "responses_posts",
            "active",
            "finished",
            "auth_rejected",
            "invalid_requests",
            "unknown_scenarios",
            "unmarked_requests",
            "registered_requests",
        }
        if not isinstance(value, dict) or set(value) != fields | {"saturated"} or value.get("saturated") is not False:
            raise LiveSafetyError("Provider global counters are unavailable or saturated")
        if any(type(value[key]) is not int or not 0 <= value[key] <= 2**63 - 1 for key in fields):
            raise LiveSafetyError("Provider global counters have an invalid shape")
        if (
            value["model_posts"] != value["chat_posts"] + value["responses_posts"]
            or value["model_posts"] != value["active"] + value["finished"]
        ):
            raise LiveSafetyError("Provider global counters are inconsistent")
        return value

    async def provider_counts(self, identifier: str) -> dict:
        self.owned.require("scenario", identifier, identifier)
        return checked_json(
            await self.control.get(f"{self.settings.provider_control_url}/__control/scenarios/{identifier}"),
            unified=False,
        )


_POLICY_FIELDS = ("enabled", "input_enabled", "output_enabled", "words_types", "custom_words", "auto_reply")


class SafetyPolicyLease:
    """CAS restore only this run's own last version; never overwrite another editor."""

    def __init__(self, http: LiveSafetyHTTP, tenant_id: int = 1):
        self.http = http
        self.tenant_id = _positive(str(tenant_id), "tenant_id")
        self.path = http.settings.api_base.removesuffix("/api/v1") + "/api/sensitive/dsh/settings"
        self.original: dict | None = None
        self.last_version: int | None = None

    async def read(self) -> dict:
        value = checked_json(await self.http.admin.get(self.path, params={"tenant_id": self.tenant_id}))
        if (
            not isinstance(value, dict)
            or type(value.get("version")) is not int
            or any(key not in value for key in _POLICY_FIELDS)
        ):
            raise LiveSafetyError("Safety policy read returned an incomplete snapshot")
        return value

    async def __aenter__(self):
        if not self.http.settings.allow_policy_mutation:
            raise LiveSafetyError("Tenant-wide policy tests require explicit exclusive-window permission")
        self.original = copy.deepcopy(await self.read())
        self.last_version = self.original["version"]
        return self

    async def save(self, **changes) -> dict:
        if self.original is None or self.last_version is None or not set(changes) <= set(_POLICY_FIELDS):
            raise LiveSafetyError("Safety policy lease is inactive or has invalid changes")
        before = await self.read()
        if before["version"] != self.last_version:
            raise LiveSafetyError("Safety policy changed outside this test run; automatic writes stopped")
        desired = {key: copy.deepcopy(before[key]) for key in _POLICY_FIELDS} | changes
        result = checked_json(
            await self.http.admin.put(
                self.path, params={"tenant_id": self.tenant_id}, json={"expected_version": self.last_version, **desired}
            )
        )
        if (
            not isinstance(result, dict)
            or type(result.get("version")) is not int
            or result["version"] != self.last_version + 1
        ):
            raise LiveSafetyError("Safety policy write did not confirm the next CAS version")
        self.last_version = result["version"]
        after = await self.read()
        if after["version"] != self.last_version or any(after[key] != desired[key] for key in _POLICY_FIELDS):
            raise LiveSafetyError("Safety policy GET did not confirm the committed write")
        return after

    async def __aexit__(self, *_):
        if self.original is not None:
            current = await self.read()
            if current["version"] != self.last_version:
                raise LiveSafetyError("Safety policy ownership changed; manual restoration is required")
            if self.last_version != self.original["version"]:
                await self.save(**{key: copy.deepcopy(self.original[key]) for key in _POLICY_FIELDS})


async def wait_until(
    read: Callable[[], Awaitable[object]], predicate: Callable[[object], bool], *, timeout: float = 30
):
    """Bound asynchronous projection waits without printing raw responses."""
    if not 0 < timeout <= 120:
        raise LiveSafetyError("Invalid live readback deadline")
    deadline = time.monotonic() + timeout
    while True:
        result = await read()
        if predicate(result):
            return result
        if time.monotonic() >= deadline:
            raise LiveSafetyError("Live readback did not converge before its deadline")
        await asyncio.sleep(min(0.25, max(0, deadline - time.monotonic())))
