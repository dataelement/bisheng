"""The capability bus — what a hosted application may call, and as whom (F055 T056-T058).

An application declares capabilities in ``bisheng-app.yaml``; the platform is
the one that decides what those words are worth at runtime. This module is that
decision, and it has exactly three jobs:

* **Model injection (T056 / AC-49 / AC-51 / AC-54).** The application talks to
  F051's OpenAI-compatible face with an industry-standard client and the four
  environment variables :func:`runtime_capability_env` produces. It never
  configures a provider account or an endpoint of its own — there is no
  workbench surface that would let it, and there is no code path here that
  reads one. The callable range is the effective declaration, enforced by
  F051 through :class:`HostedAppDeclarationAdapter`.
* **Knowledge injection and fail-closed (T057 / AC-50 / AC-52).** The whitelist
  comes from the **currently effective declaration** — the version the
  application is actually running — and never from anything the application
  sends. The reachable set is ``whitelist ∩ the access user's visible scope``,
  computed file-by-file by F052's facade. No access user, no retrieval: there
  is no fallback to the owner, to "everything declared", or to a public subset.
* **Revocation, computed rather than stored (T058 / AC-53 / AC-63).** Nothing
  writes "this capability died"; :func:`capability_status` re-derives it from
  the declaration and the platform's current state whenever the publish surface
  or an approval card asks. There is no timer and no cached verdict, so there
  is nothing that can drift.

Three decisions worth not re-litigating:

* **The effective declaration is read off ``app.current_version_id``**, not off
  the latest version row and not off a cache. That is what makes AC-37's
  five-second bound true for free: the moment an iteration goes online, the
  pointer moves and the next call reads the new declaration. A cache here would
  need its own invalidation story and would be the only thing standing between
  a revoked model and a call that still works.
* **Model refusals keep F051's 265 codes; knowledge refusals get 162** (design
  D13). A model refusal is rendered as an OpenAI error body by the face that
  raises it; re-coding it here would strip that rendering and give an agent a
  number its client cannot classify.
* **The scopes derived here are validated against what this deployment can
  actually issue.** ``model:invoke`` is an extension scope gated on
  ``open_platform.enabled``; a declaration that needs a scope the deployment
  does not offer is refused at publish time (16231) rather than deployed into
  an application whose every model call answers 403.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

from loguru import logger

from bisheng.app_publish.application.reference_access import (
    get_hosted_app_reference_runtime,
    get_hosted_app_user_reference_runtime,
)
from bisheng.app_publish.domain.repositories.reference_source_repository import HostedAppReferenceSourceRepository
from bisheng.app_publish.domain.schemas.app_manifest import CapabilityDeclaration
from bisheng.app_publish.domain.services.app_credential_service import (
    HOSTED_APP_TOKEN_ENV,
    AppRuntimeCredentialService,
)
from bisheng.app_publish.domain.services.reference_extractor import extract_app_reference_requests
from bisheng.common.errcode.app_publish import (
    AppCapabilityNotDeclaredError,
    AppCapabilityRevokedError,
)
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.common.errcode.mcp_face import KnowledgeCapabilityRevokedError
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.llm.application.model_name_resolution import get_model_name_resolution_port
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.scopes import is_scope_issuable
from bisheng.open_api.domain.services.public_base_url import MODEL_GATEWAY_BASE_PATH
from bisheng.resource_reference.application.contracts import SourceType, TargetType
from bisheng.resource_reference.application.source_contracts import SourceReadRequest

#: API capability kinds. Secret references grant no Open API scope.
CAPABILITY_KIND_MODEL = "model"
CAPABILITY_KIND_KNOWLEDGE = "knowledge"

#: Open-API scopes each kind derives (design D13). Nothing else is derived —
#: an application never gets a write scope from a declaration.
MODEL_SCOPE = "model:invoke"
KNOWLEDGE_SCOPE = "knowledge:read"

#: Environment names of the model face, defined by F051 design D2 and copied
#: into F054's ``contracts-runtime-manager.md`` §5. ``OPENAI_*`` is what the
#: official client reads with zero configuration; the ``BISHENG_`` twin exists
#: for engines and skill packs that do not follow the OpenAI convention.
MODEL_BASE_URL_ENV = "OPENAI_BASE_URL"
MODEL_API_KEY_ENV = "OPENAI_API_KEY"
MODEL_BASE_URL_RESERVED_ENV = "BISHENG_MODEL_BASE_URL"

#: ``reason`` vocabulary of :class:`CapabilityStatus` and of 16273's payload.
REASON_OK = "ok"
REASON_REVOKED = "revoked"
REASON_AMBIGUOUS = "ambiguous"
REASON_UNRESOLVABLE = "unresolvable"


@dataclass(frozen=True, slots=True)
class DeclaredKnowledge:
    """One ``capabilities.knowledge_bases[]`` entry, resolved or not.

    ``label`` is what the owner wrote — the id when they gave one, the name
    otherwise. Every message about this capability uses it, because a number
    the owner never typed is not an answer to "which one broke".
    """

    label: str
    knowledge_id: int | None = None
    knowledge_name: str = ""
    reason: str = REASON_OK

    @property
    def resolved(self) -> bool:
        return self.knowledge_id is not None and self.reason == REASON_OK


@dataclass(frozen=True, slots=True)
class EffectiveDeclaration:
    """What the running version declared, resolved against the platform today."""

    app_id: str
    tenant_id: int
    version_id: str
    app_name: str = ""
    models: tuple[str, ...] = ()
    knowledge: tuple[DeclaredKnowledge, ...] = ()

    @property
    def model_names(self) -> frozenset[str]:
        return frozenset(self.models)

    @property
    def knowledge_whitelist(self) -> list[int]:
        """Runtime uses the entire saved source; invalid references cannot drop out."""
        if any(not one.resolved for one in self.knowledge):
            raise ResourceReferenceInvalidError(reason="app_knowledge_reference_invalid")
        return [one.knowledge_id for one in self.knowledge]

    def is_empty(self) -> bool:
        return not self.models and not self.knowledge


@dataclass(frozen=True, slots=True)
class CapabilityStatus:
    """One row of the publish surface's capability list (AC-63) / approval card (AC-24)."""

    kind: str
    label: str
    display_name: str
    revoked: bool = False
    reason: str = REASON_OK
    detail: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Reading the effective declaration
# ---------------------------------------------------------------------------


def parse_declaration(capabilities) -> CapabilityDeclaration:
    """The frozen ``capabilities`` blob as the manifest model, never as a raw dict.

    Frozen JSON is read back with the same schema that validated it, so a field
    renamed in the schema cannot be silently missed by a reader that indexed the
    dict by hand.
    """

    if isinstance(capabilities, CapabilityDeclaration):
        return capabilities
    if not isinstance(capabilities, dict) or not capabilities:
        return CapabilityDeclaration()
    try:
        return CapabilityDeclaration.model_validate(capabilities)
    except Exception:
        # A frozen declaration this platform can no longer parse is a capability
        # set we must not guess at: answer "declared nothing", which fails every
        # call closed rather than opening one by accident.
        logger.exception("app_publish.capability_declaration_unreadable payload_keys={}", sorted(capabilities))
        return CapabilityDeclaration()


async def _read_effective_source(session, app_id, principal, *, purpose):
    from bisheng.open_api.application.access_context import get_current_open_api_principal

    actual = get_current_open_api_principal()
    principal = actual if principal is None else principal
    if (
        not isinstance(principal, OpenApiPrincipal)
        or principal is not actual
        or principal.actor_kind != "hosted_app"
        or principal.subject_ref != app_id
    ):
        raise ResourceReferenceInvalidError(reason="app_runtime_principal_required")
    runtime = await get_hosted_app_reference_runtime()
    scope = await runtime.verifier.aissue_scope(
        session, SourceReadRequest(SourceType.HOSTED_APP_VERSION, app_id, purpose=purpose), principal
    )
    result = (
        await runtime.arequire_source_valid(session, scope, principal)
        if purpose == "execute"
        else await runtime.ainspect_source(session, scope, principal)
    )
    return runtime, result, principal


async def _knowledge_names(session, snapshot):
    # Names decorate already-admitted exact IDs; this observation adds no locks
    # or authority and never participates in the frozen configuration digest.
    knowledge_ids = tuple(
        int(one.target.target_id) for one in snapshot.references if one.target.target_type == TargetType.KNOWLEDGE_SPACE
    )
    if not knowledge_ids:
        return {}
    return {
        str(row["id"]): row["name"]
        for row in await HostedAppReferenceSourceRepository().aget_knowledge_candidates(session, ids=knowledge_ids)
    }


async def _effective_from_source(session, result):
    snapshot = result.snapshot
    payload = json.loads(snapshot.payload_json)
    declaration = CapabilityDeclaration.model_validate(payload["capabilities"])
    frozen = {one.slot_key: one.target for one in snapshot.references}
    facts = {one.key: one for one in result.target_states}
    labels = _declaration_labels(declaration)
    named = await _knowledge_names(session, snapshot)
    knowledge = []
    for request in _ordered_requests(declaration):
        if request.target_type != TargetType.KNOWLEDGE_SPACE:
            continue
        target = frozen[request.slot_key]
        fact = facts[target]
        knowledge.append(
            DeclaredKnowledge(
                label=labels[request.slot_key],
                knowledge_id=int(target.target_id),
                knowledge_name=named.get(target.target_id) or request.requested_name or "",
                reason=REASON_OK if fact.is_valid else REASON_REVOKED,
            )
        )
    return EffectiveDeclaration(
        app_id=snapshot.source_key.source_id,
        tenant_id=snapshot.source_key.tenant_id,
        version_id=snapshot.source_key.source_version,
        app_name=payload["root"]["name"] or "",
        models=tuple(dict.fromkeys(ref.name for ref in declaration.models if ref.name)),
        knowledge=tuple(knowledge),
    )


async def load_effective_declaration(app_id: str, *, principal=None, purpose="execute", session=None):
    """Read the actual credential's saved version and frozen IDs, without re-resolution.

    Execute validates every reference. Inspection is metadata only and retains invalid IDs.
    An external Session must already have a transaction; its caller owns finalization.
    """
    if session is not None:
        _, result, _ = await _read_effective_source(session, app_id, principal, purpose=purpose)
        return await _effective_from_source(session, result)
    async with get_async_db_session() as owned, owned.begin():
        _, result, _ = await _read_effective_source(owned, app_id, principal, purpose=purpose)
        return await _effective_from_source(owned, result)


def _declaration_labels(declaration):
    labels = {}
    for one in declaration.models:
        for request in extract_app_reference_requests(CapabilityDeclaration(models=[one])):
            labels.setdefault(request.slot_key, one.name)
    for one in declaration.knowledge_bases:
        for request in extract_app_reference_requests(CapabilityDeclaration(knowledge_bases=[one])):
            labels.setdefault(request.slot_key, (one.id or one.name or "").strip())
    return labels


def _ordered_requests(declaration):
    requests = {one.slot_key: one for one in extract_app_reference_requests(declaration)}
    return tuple(requests[slot] for slot in _declaration_labels(declaration))


def unready_saved_capabilities(capabilities):
    """Retain declaration rows when its index/catalog cannot be inspected; never invent IDs."""
    try:
        declaration = CapabilityDeclaration.model_validate(capabilities or {})
        labels = _declaration_labels(declaration)
        requests = _ordered_requests(declaration)
    except (TypeError, ValueError):
        return (CapabilityStatus("configuration", "capabilities", "capabilities", True, "not_ready"),)
    return tuple(
        CapabilityStatus(
            CAPABILITY_KIND_MODEL if one.target_type == TargetType.MODEL else CAPABILITY_KIND_KNOWLEDGE,
            labels[one.slot_key],
            labels[one.slot_key],
            True,
            "not_ready",
            {"target_id": one.target_id, "target_type": one.target_type.value, "state": "not_ready"},
        )
        for one in requests
    )


async def inspect_saved_capabilities(app_id, version_id, identity, *, session=None):
    """Observe a real saved source and its frozen IDs, without execution authority."""
    if session is None:
        async with get_async_db_session() as owned, owned.begin():
            return await inspect_saved_capabilities(app_id, version_id, identity, session=owned)
    runtime = await get_hosted_app_user_reference_runtime()
    scope = await runtime.verifier.aissue_scope(
        session, SourceReadRequest(SourceType.HOSTED_APP_VERSION, app_id, version_id, purpose="inspect"), identity
    )
    result = await runtime.ainspect_source(session, scope, identity)
    snapshot = result.snapshot
    declaration = CapabilityDeclaration.model_validate(json.loads(snapshot.payload_json)["capabilities"])
    references = {one.slot_key: one.target for one in snapshot.references}
    states = {one.key: one for one in result.target_states}
    requests = _ordered_requests(declaration)
    labels = _declaration_labels(declaration)
    knowledge_names = await _knowledge_names(session, snapshot)
    requested_names = tuple(sorted({one.requested_name for one in requests if one.target_type == TargetType.MODEL}))
    unavailable = False
    try:
        observations = {
            one.requested: one
            for one in await get_model_name_resolution_port().ainspect_model_names_current(
                session, snapshot.source_key.tenant_id, requested_names, identity=identity
            )
        }
    except Exception:
        logger.exception("app_publish.saved_capability_observation_failed app_id={} version_id={}", app_id, version_id)
        observations, unavailable = {}, True
    rows = []
    for request in requests:
        target = references[request.slot_key]
        fact = states[target]
        model = request.target_type == TargetType.MODEL
        reason = REASON_OK if fact.is_valid else fact.state.value
        revoked = not fact.is_valid
        if model:
            observed = observations.get(request.requested_name)
            if observed is None:
                unavailable = True
            elif observed.status != "valid":
                revoked, reason = True, observed.status
            elif observed.resolved.model_id != int(target.target_id):
                revoked, reason = True, "binding_identity_changed"
        label = labels[request.slot_key]
        rows.append(
            CapabilityStatus(
                CAPABILITY_KIND_MODEL if model else CAPABILITY_KIND_KNOWLEDGE,
                label,
                knowledge_names.get(target.target_id, label) if not model and fact.is_valid else label,
                revoked,
                reason,
                {"target_id": target.target_id, "target_type": target.target_type.value, "state": fact.state.value},
            )
        )
    if unavailable:
        return tuple(
            CapabilityStatus(row.kind, row.label, row.display_name, True, "not_ready", row.detail) for row in rows
        )
    return tuple(rows)


async def _resolve_knowledge_refs(
    declaration: CapabilityDeclaration,
    *,
    tenant_id: int,
) -> tuple[DeclaredKnowledge, ...]:
    """Turn ``{id}`` / ``{name}`` references into knowledge ids, one batch each.

    A reference by name is resolved against the tenant's knowledge bases, and a
    name that now matches several is **ambiguous**, not "the first one" — the
    same rule F051 applies to a bare model name, and for the same reason: a
    retrieval silently bound to whichever base was created first is a data leak
    that nobody can see.
    """

    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
    from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService

    refs = list(declaration.knowledge_bases)
    if not refs:
        return ()

    wanted_ids = {int(ref.id) for ref in refs if _looks_numeric(ref.id)}
    wanted_names = {ref.name.strip() for ref in refs if not _looks_numeric(ref.id) and (ref.name or "").strip()}

    with _as_tenant(tenant_id):
        rows_by_id = {row.id: row for row in (await KnowledgeDao.aget_list_by_ids(sorted(wanted_ids)))}
        by_name: dict[str, list] = {}
        if wanted_names:
            for row in await KnowledgeDao.aget_by_exact_names(sorted(wanted_names)):
                by_name.setdefault(row.name or "", []).append(row)

    resolved: list[DeclaredKnowledge] = []
    for ref in refs:
        label = (ref.id or ref.name or "").strip()
        if _looks_numeric(ref.id):
            row = rows_by_id.get(int(ref.id))
            if row is None or not RetrievalFacadeService.is_supported_knowledge_type(row.type):
                # Unsupported type answers exactly like "gone": telling the two
                # apart would let a declaration probe for the existence of a
                # knowledge base the owner may not see.
                resolved.append(DeclaredKnowledge(label=label, reason=REASON_REVOKED))
                continue
            resolved.append(DeclaredKnowledge(label=label, knowledge_id=row.id, knowledge_name=row.name or ""))
            continue

        candidates = [
            row for row in by_name.get(label, []) if RetrievalFacadeService.is_supported_knowledge_type(row.type)
        ]
        if not candidates:
            resolved.append(DeclaredKnowledge(label=label, reason=REASON_REVOKED))
        elif len(candidates) > 1:
            resolved.append(DeclaredKnowledge(label=label, reason=REASON_AMBIGUOUS))
        else:
            row = candidates[0]
            resolved.append(DeclaredKnowledge(label=label, knowledge_id=row.id, knowledge_name=row.name or ""))
    return tuple(resolved)


def _looks_numeric(value: str | None) -> bool:
    return bool(value) and str(value).strip().lstrip("-").isdigit()


@contextmanager
def _as_tenant(tenant_id: int):
    """Run a knowledge read inside the **application's** tenant, not the caller's.

    The bus is reached from a Celery worker (publish) and from an ``/api/v2``
    request whose ambient tenant is the credential's. Those agree today, but the
    declaration belongs to the application's tenant and that is the one whose
    knowledge bases may be named — so it is set explicitly rather than inherited.
    Same shape as ``model_catalog._as_tenant``, minus the admin-scope reset: this
    path is never reached from the F019 management view.
    """

    token = current_tenant_id.set(int(tenant_id))
    try:
        yield
    finally:
        current_tenant_id.reset(token)


# ---------------------------------------------------------------------------
# T056 — model capability injection
# ---------------------------------------------------------------------------


class HostedAppDeclarationAdapter:
    """F051's ``HostedAppDeclarationPort`` — "which models may this app call".

    ``None`` is F051's "cannot tell right now" and makes the face answer 26516
    without calling anything. An empty frozenset is "declared zero models", which
    refuses every name with 26515 instead — two different fixes, two different
    answers.
    """

    async def declared_model_names(self, app_id: str, tenant_id: int) -> frozenset[str] | None:
        declaration = await load_effective_declaration(app_id, purpose="inspect")
        if declaration is None or declaration.tenant_id != int(tenant_id):
            return None
        return declaration.model_names

    async def assert_model_binding(self, principal, requested, resolved) -> None:
        async with get_async_db_session() as session, session.begin():
            runtime, result, original = await _read_effective_source(
                session, principal.subject_ref, principal, purpose="execute"
            )
            await runtime.source_owner.assert_model_binding_current(
                session, result.snapshot, original, requested, resolved
            )


def derive_scopes(declaration: CapabilityDeclaration) -> list[str]:
    """Open-API scopes a declaration buys. Secrets grant no scopes.

    Order is fixed so the issued credential's scope list is stable across
    publishes of the same declaration — an unstable list would make every
    re-issue look like a change in the audit trail.
    """

    scopes: list[str] = []
    if declaration.models:
        scopes.append(MODEL_SCOPE)
    if declaration.knowledge_bases:
        scopes.append(KNOWLEDGE_SCOPE)
    return scopes


def undeployable_scopes(declaration: CapabilityDeclaration) -> list[str]:
    """Scopes this declaration needs that this deployment cannot issue.

    ``model:invoke`` is an extension scope behind ``open_platform.enabled``. A
    declaration that needs one is refused at publish time — see the module
    docstring for why deploying it anyway is worse.
    """

    from bisheng.open_api.domain.scopes import OPEN_API_SCOPE_MAP

    refused = []
    for code in derive_scopes(declaration):
        scope = OPEN_API_SCOPE_MAP.get(code)
        if scope is None or not is_scope_issuable(scope):
            refused.append(code)
    return refused


def model_face_base_url() -> str:
    """The OpenAI-compatible base URL injected into a container.

    Request-free by construction: this runs on the Celery worker that brings the
    approved version online, where there is no ``Request`` to read forwarding
    headers off. ``open_api.public_base_url`` is the operator-declared
    browser-facing address and is the right answer whenever it is set;
    ``app_runtime.entry_base_url`` is the same address seen from the entry side
    and is the honest fallback. An empty result is returned as an empty string
    rather than a guess — the container then has no model base URL, which fails
    visibly at the first call instead of dialling an address nobody serves.
    """

    base = (settings.open_api.public_base_url or "").strip().rstrip("/")
    if not base:
        base = (settings.app_runtime.entry_base_url or "").strip().rstrip("/")
    if not base:
        logger.warning(
            "app_publish.capability_bus model base URL is undeterminable — set open_api.public_base_url "
            "(or app_runtime.entry_base_url); hosted applications will start without {}",
            MODEL_BASE_URL_ENV,
        )
        return ""
    return f"{base}{MODEL_GATEWAY_BASE_PATH}"


async def runtime_capability_env(app_id: str, *, declaration: CapabilityDeclaration | None = None) -> dict[str, str]:
    """Issue this application's runtime credential and return the env to inject.

    Called immediately before the container is created (design D13): re-issuing
    revokes whatever the previous instance held, and the five-second bound on
    the old key is the credential cache TTL, not a sweep.

    ``declaration`` is the version about to run — passed in by the caller, which
    has the row in hand, rather than read back through
    :func:`load_effective_declaration`: at this moment ``current_version_id``
    still points at the *previous* version, so reading it would derive the old
    version's scopes for the new container.
    """

    declared = declaration if declaration is not None else CapabilityDeclaration()
    token = await AppRuntimeCredentialService.issue(app_id, scopes=derive_scopes(declared))
    env = {HOSTED_APP_TOKEN_ENV: token}
    if declared.models:
        base_url = model_face_base_url()
        env[MODEL_API_KEY_ENV] = token
        if base_url:
            env[MODEL_BASE_URL_ENV] = base_url
            env[MODEL_BASE_URL_RESERVED_ENV] = base_url
    return env


# ---------------------------------------------------------------------------
# T057 — knowledge capability injection, fail-closed
# ---------------------------------------------------------------------------


def hosted_app_access_user(request, principal) -> int | None:
    """The visitor a hosted application's request is being made for, or ``None``.

    Reads the one header F054 injects per visit and verifies it through the very
    port F051's model face verifies it with, so "who is this call for" has one
    answer on both faces. ``None`` means "no verifiable access user" — a missing
    header, an expired or forged token, or a token minted for a different
    application — and every caller must turn that into a refusal rather than
    into the owner, the application itself, or anonymity.
    """

    from bisheng.open_api.domain.services.model_range_policy import (
        ACCESS_TOKEN_HEADER,
        get_access_subject_verifier,
    )

    headers = getattr(request, "headers", None)
    token = headers.get(ACCESS_TOKEN_HEADER) if headers is not None else None
    if not token:
        return None
    verified = get_access_subject_verifier().verify(
        token,
        app_id=principal.subject_ref or "",
        tenant_id=principal.tenant_id,
    )
    if principal.preview_session_id:
        if verified is None or (verified.user_id, verified.preview_session) != (
            principal.preview_viewer_user_id,
            principal.preview_session_id,
        ):
            return None
        return principal.preview_capability_user_id
    if getattr(verified, "preview_session", None):
        return None
    return verified.user_id if verified is not None else None


class CapabilityBusService:
    """The runtime entry every hosted-application capability call goes through."""

    @classmethod
    async def retrieve(
        cls,
        *,
        app_id: str,
        access_user_id: int | None,
        query: str,
        knowledge_ids: Sequence[int] | None = None,
        top_k: int = 10,
        max_content: int = 15000,
        tag_filters: dict | None = None,
        credential_id: int | None = None,
        version_repo=None,
        principal=None,
    ):
        """Search, as the access user, inside the application's declared scope.

        The two inputs that decide what comes back are both taken from the
        platform: the whitelist from the effective declaration, and the visible
        scope from the access user's own grants. The application contributes the
        query and, optionally, a narrowing subset of ids — never a widening one,
        because anything outside the whitelist is dropped by the facade before a
        permission is even checked.

        ``access_user_id is None`` is a refusal (AC-52). It is expressed by
        handing the facade no identity, which raises 26320 — one implementation
        of "no identity, no retrieval" rather than two that can disagree.
        """

        from bisheng.knowledge.domain.schemas.retrieval_facade import RetrievalIdentity, RetrievalRequest
        from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService

        declaration = await cls._require_declaration(app_id, principal=principal)
        whitelist = declaration.knowledge_whitelist

        started = time.monotonic()
        try:
            # Inside the recorded span on purpose: a call refused because the
            # application named an undeclared or revoked knowledge base is still
            # a call that application made on somebody's behalf, and AC-55's
            # ledger is where "it kept asking for 财务档案" becomes visible. A
            # refusal raised one layer deeper (26322 from the facade) is already
            # recorded, so leaving this one out would make the table's answer to
            # "what did this app try" depend on which layer said no.
            cls._assert_targets_declared(declaration, knowledge_ids)
        except BaseErrorCode as exc:
            await cls._record(
                declaration, access_user_id, knowledge_ids, None, started, error=exc, credential_id=credential_id
            )
            raise

        identity = None
        if access_user_id:
            identity = await RetrievalIdentity.from_user(int(access_user_id), declaration.tenant_id)

        try:
            result = await RetrievalFacadeService.retrieve(
                identity,
                RetrievalRequest(
                    query=query,
                    knowledge_ids=[int(one) for one in knowledge_ids] if knowledge_ids else None,
                    whitelist=whitelist,
                    top_k=top_k,
                    max_content=max_content,
                    tag_filters=tag_filters,
                ),
                version_repo=version_repo,
            )
        except KnowledgeCapabilityRevokedError as exc:
            revoked = cls._as_revoked(declaration, exc)
            await cls._record(
                declaration, access_user_id, knowledge_ids, None, started, error=revoked, credential_id=credential_id
            )
            raise revoked from exc
        except BaseErrorCode as exc:
            await cls._record(
                declaration, access_user_id, knowledge_ids, None, started, error=exc, credential_id=credential_id
            )
            raise

        await cls._record(declaration, access_user_id, knowledge_ids, result, started, credential_id=credential_id)
        return result

    @classmethod
    async def accessible_knowledge(cls, *, app_id: str, access_user_id: int | None, principal=None):
        """The declared knowledge bases this access user can actually reach.

        Same two-sided narrowing as :meth:`retrieve`, which is what makes AC-50's
        set-equality assertion checkable: this returns the intersection, and the
        user's own in-platform list returns their side of it.
        """

        from bisheng.knowledge.domain.schemas.retrieval_facade import RetrievalIdentity
        from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService

        declaration = await cls._require_declaration(app_id, principal=principal)
        identity = None
        if access_user_id:
            identity = await RetrievalIdentity.from_user(int(access_user_id), declaration.tenant_id)
        report = await RetrievalFacadeService.check_reachable(
            identity,
            declaration.knowledge_whitelist,
            whitelist=declaration.knowledge_whitelist,
        )
        return report

    # -- helpers ---------------------------------------------------------

    @staticmethod
    async def _record(
        declaration: EffectiveDeclaration,
        access_user_id: int | None,
        requested,
        result,
        started: float,
        *,
        error: BaseErrorCode | None = None,
        credential_id: int | None = None,
    ) -> None:
        """Write the dual-attribution record (AC-55), refusals included.

        A refusal with **no** access user writes nothing: there is no subject to
        attribute it to, and inventing one is precisely what AC-55 forbids. The
        refusal itself is not lost — the facade raised 26320 and the caller sees
        it — it simply has no place in a table whose rows are "application X
        searched on behalf of person Y".
        """

        if not access_user_id:
            return
        from bisheng.app_publish.domain.services import capability_audit
        from bisheng.open_api.application.access_context import get_current_open_api_principal

        principal = get_current_open_api_principal()
        audit_user = principal.preview_viewer_user_id if principal and principal.preview_session_id else access_user_id
        await capability_audit.record_retrieval(
            app_id=declaration.app_id,
            app_name=declaration.app_name,
            tenant_id=declaration.tenant_id,
            version_id=declaration.version_id,
            credential_id=credential_id,
            access_user_id=int(audit_user),
            requested=[int(one) for one in (requested or [])],
            effective=list(getattr(result, "effective_scope", []) or []),
            result=capability_audit.RESULT_SUCCESS if error is None else capability_audit.RESULT_REFUSED,
            error_code=getattr(error, "code", None),
            chunk_count=int(getattr(result, "total", 0) or 0) if result is not None else None,
            latency_ms=max(int((time.monotonic() - started) * 1000), 0),
        )

    @staticmethod
    async def _require_declaration(app_id: str, *, principal=None) -> EffectiveDeclaration:
        declaration = await load_effective_declaration(app_id, principal=principal)
        if declaration is None:
            # The application is not online, or vanished between the request
            # arriving and this read. Either way it holds no capability now.
            raise AppCapabilityNotDeclaredError(capability=CAPABILITY_KIND_KNOWLEDGE, kind=CAPABILITY_KIND_KNOWLEDGE)
        return declaration

    @staticmethod
    def _assert_targets_declared(declaration: EffectiveDeclaration, knowledge_ids: Sequence[int] | None) -> None:
        """AC-51: a knowledge base the user can see but the app never declared is refused.

        Answered before the facade runs so the refusal names the capability
        rather than arriving as one undifferentiated "unreachable" among several.
        """

        if not knowledge_ids:
            return
        allowed = set(declaration.knowledge_whitelist)
        declared_but_broken = {one.label for one in declaration.knowledge if not one.resolved}
        for raw in knowledge_ids:
            target = int(raw)
            if target in allowed:
                continue
            if str(target) in declared_but_broken:
                raise AppCapabilityRevokedError(
                    capability=str(target),
                    kind=CAPABILITY_KIND_KNOWLEDGE,
                    reason=REASON_REVOKED,
                    knowledge_id=target,
                )
            raise AppCapabilityNotDeclaredError(capability=str(target), kind=CAPABILITY_KIND_KNOWLEDGE)

    @staticmethod
    def _as_revoked(declaration: EffectiveDeclaration, exc: KnowledgeCapabilityRevokedError):
        """26322 → 16273, carrying the label the owner wrote (AC-53).

        The facade's code is right for its own callers; this one is the
        application's, and the application's owner recognises their own
        ``knowledge_bases[]`` entry, not the numeric id the facade reports.
        """

        knowledge_id = exc.kwargs.get("knowledge_id")
        label = str(knowledge_id)
        for one in declaration.knowledge:
            if one.knowledge_id == knowledge_id:
                label = one.knowledge_name or one.label
                break
        return AppCapabilityRevokedError(
            capability=label,
            kind=CAPABILITY_KIND_KNOWLEDGE,
            reason=REASON_REVOKED,
            knowledge_id=knowledge_id,
        )


# ---------------------------------------------------------------------------
# T060 — reference validation at precheck
# ---------------------------------------------------------------------------


async def validate_capability_refs(
    declaration: CapabilityDeclaration,
    *,
    tenant_id: int,
    owner_user_id: int,
) -> None:
    """Refuse a declaration whose references do not resolve (AC-07, 16224).

    Both halves go through the component that will serve them at runtime, never
    through a query of this module's own:

    * a **model** is resolved by ``model_catalog.resolve_model_name`` — F051's
      rules, so "enabled in this tenant" and "this bare name is ambiguous, use
      the qualified one" have one definition. A precheck with its own SELECT
      would eventually pass something the face refuses, which is the worst kind
      of green;
    * a **knowledge base** is checked against
      ``RetrievalFacadeService.is_supported_knowledge_type`` and
      ``check_reachable``, for the same reason (T060 dependency note).

    Reachability is judged **as the owner**, because the owner's grants are the
    ceiling the declaration narrows (design D13). It is not judged as any access
    user: those differ per visit, and a declaration that only validated for
    whoever happens to open the app first would be meaningless.
    """

    from bisheng.common.errcode.app_publish import AppCapabilityUnresolvableError
    from bisheng.common.errcode.model_face import ModelFaceError, ModelFaceModelAmbiguousError
    from bisheng.knowledge.domain.schemas.retrieval_facade import RetrievalIdentity
    from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService
    from bisheng.llm.domain.services.model_catalog import resolve_model_name

    if declaration.is_empty():
        return

    for ref in declaration.models:
        try:
            await resolve_model_name(int(tenant_id), ref.name)
        except ModelFaceModelAmbiguousError as exc:
            raise AppCapabilityUnresolvableError(
                msg=f"模型 {ref.name} 在本租户下有多个同名配置, 无法唯一确定",
                details={
                    "field": "capabilities.models",
                    "value": ref.name,
                    "reason": "model_ambiguous",
                    "candidates": list(getattr(exc, "candidates", []) or []),
                },
                hints=[
                    "请改用「服务商名/模型名」的限定名, 例如 "
                    + next(iter(getattr(exc, "candidates", []) or ["提供商/模型"]))
                ],
            ) from exc
        except ModelFaceError as exc:
            raise AppCapabilityUnresolvableError(
                msg=f"模型 {ref.name} 在本租户不可用",
                details={
                    "field": "capabilities.models",
                    "value": ref.name,
                    "reason": "model_unavailable",
                    "upstream_code": exc.code,
                },
                hints=["请在模型管理页确认该模型已启用, 或改用已启用的模型名后重新发布"],
            ) from exc

    resolved = await _resolve_knowledge_refs(declaration, tenant_id=int(tenant_id))
    broken = [one for one in resolved if not one.resolved]
    if broken:
        first = broken[0]
        raise AppCapabilityUnresolvableError(
            msg=f"知识库 {first.label} 无法解析",
            details={
                "field": "capabilities.knowledge_bases",
                "value": first.label,
                "reason": f"knowledge_{first.reason}",
                "unresolved": [one.label for one in broken],
            },
            hints=(
                ["同名知识库不止一个, 请改用 id 引用"]
                if first.reason == REASON_AMBIGUOUS
                else ["请确认知识库存在, 且类型为文档知识库或知识空间(问答库暂不支持检索)"]
            ),
        )

    whitelist = [one.knowledge_id for one in resolved if one.resolved]
    if not whitelist:
        return
    identity = await RetrievalIdentity.from_user(int(owner_user_id), int(tenant_id))
    report = await RetrievalFacadeService.check_reachable(identity, whitelist, whitelist=whitelist)
    unreachable = sorted(set(report.unreachable) | set(report.revoked))
    if unreachable:
        raise AppCapabilityUnresolvableError(
            msg="声明的知识库中有当前归属人无权检索的项",
            details={
                "field": "capabilities.knowledge_bases",
                "reason": "knowledge_unreachable",
                "unreachable": unreachable,
            },
            hints=["请先在知识库权限中把这些知识库授权给应用归属人, 再重新发布"],
        )


# ---------------------------------------------------------------------------
# T058 — 「已失效 + 原因」, computed on demand
# ---------------------------------------------------------------------------


async def capability_status(
    *,
    app_id: str | None = None,
    tenant_id: int | None = None,
    capabilities=None,
) -> list[CapabilityStatus]:
    """The capability list a publish surface or an approval card renders.

    Two call shapes, one answer: ``app_id`` reads the running version's
    declaration, and ``capabilities`` + ``tenant_id`` describes a version that is
    not running yet (the approval card, AC-24). Nothing is persisted and no timer
    is started — the marks are re-derived per request, which is why they can
    never be stale.
    """

    if capabilities is not None:
        declaration = parse_declaration(capabilities)
        resolved = await _resolve_knowledge_refs(declaration, tenant_id=int(tenant_id or 0))
        models = tuple(dict.fromkeys(ref.name for ref in declaration.models if ref.name))
        effective = EffectiveDeclaration(
            app_id=str(app_id or ""),
            tenant_id=int(tenant_id or 0),
            version_id="",
            models=models,
            knowledge=resolved,
        )
    else:
        loaded = await load_effective_declaration(str(app_id or ""))
        if loaded is None:
            return []
        effective = loaded

    rows = [_model_status(effective, name) for name in effective.models]
    rows.extend(_knowledge_status(one) for one in effective.knowledge)
    return rows


def _model_status(declaration: EffectiveDeclaration, name: str) -> CapabilityStatus:
    """Whether a declared model still resolves, judged by F051's own rules.

    Deliberately synchronous and shape-only: resolving the name for real needs
    the catalog, which the caller of this function (a page render) should not pay
    for per row. The live verdict is :func:`model_capability_status`, used where
    the caller is willing to wait.
    """

    return CapabilityStatus(
        kind=CAPABILITY_KIND_MODEL,
        label=name,
        display_name=name,
        detail={"app_id": declaration.app_id},
    )


def _knowledge_status(one: DeclaredKnowledge) -> CapabilityStatus:
    return CapabilityStatus(
        kind=CAPABILITY_KIND_KNOWLEDGE,
        label=one.label,
        display_name=one.knowledge_name or one.label,
        revoked=not one.resolved,
        reason=one.reason,
        detail={"knowledge_id": one.knowledge_id},
    )


async def model_capability_status(declaration: EffectiveDeclaration) -> list[CapabilityStatus]:
    """Live 「已失效」 verdicts for the declared models (AC-63).

    Resolution goes through F051's catalog, never a query of its own: "is this
    model callable" must have one definition, or the publish surface will show a
    model as healthy that the face refuses (or the reverse, which is worse — an
    owner republishing to fix something that was never broken).
    """

    from bisheng.common.errcode.model_face import ModelFaceError
    from bisheng.llm.domain.services.model_catalog import resolve_model_name

    rows: list[CapabilityStatus] = []
    for name in declaration.models:
        reason, revoked = REASON_OK, False
        try:
            await resolve_model_name(declaration.tenant_id, name)
        except ModelFaceError as exc:
            revoked = True
            reason = REASON_AMBIGUOUS if exc.code == 26514 else REASON_REVOKED
        rows.append(
            CapabilityStatus(
                kind=CAPABILITY_KIND_MODEL,
                label=name,
                display_name=name,
                revoked=revoked,
                reason=reason,
                detail={"app_id": declaration.app_id},
            )
        )
    return rows


__all__ = [
    "CAPABILITY_KIND_KNOWLEDGE",
    "CAPABILITY_KIND_MODEL",
    "KNOWLEDGE_SCOPE",
    "MODEL_API_KEY_ENV",
    "MODEL_BASE_URL_ENV",
    "MODEL_BASE_URL_RESERVED_ENV",
    "MODEL_SCOPE",
    "REASON_AMBIGUOUS",
    "REASON_OK",
    "REASON_REVOKED",
    "REASON_UNRESOLVABLE",
    "CapabilityBusService",
    "CapabilityStatus",
    "DeclaredKnowledge",
    "EffectiveDeclaration",
    "HostedAppDeclarationAdapter",
    "capability_status",
    "derive_scopes",
    "hosted_app_access_user",
    "load_effective_declaration",
    "model_capability_status",
    "model_face_base_url",
    "parse_declaration",
    "runtime_capability_env",
    "undeployable_scopes",
    "validate_capability_refs",
]
