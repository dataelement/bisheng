"""Real immutable APP versions, original credentials and current qualifications."""

import json
import time
from datetime import date, datetime
from types import SimpleNamespace

from pydantic import ValidationError

from bisheng.app_publish.application.reference_read_identity import (
    AppManagementSourceReadIdentity,
    AppSourceReadIdentity,
)
from bisheng.app_publish.application.reference_resolution import resolve_app_references
from bisheng.app_publish.domain.repositories.reference_source_repository import HostedAppReferenceSourceRepository
from bisheng.app_publish.domain.schemas.app_manifest import CapabilityDeclaration
from bisheng.app_publish.domain.services.preview_access_service import PreviewQualification
from bisheng.app_publish.domain.services.reference_extractor import (
    APP_REFERENCE_EXTRACTOR_VERSION,
    extract_app_reference_requests,
    extract_app_references,
)
from bisheng.app_runtime.application.authorization import authorize_loaded_app, resolve_app_actor
from bisheng.approval.application.app_review import pending_app_reviews
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.app_factory import AppNotFoundError
from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError
from bisheng.common.services.config_service import settings
from bisheng.llm.application.model_name_resolution import get_model_name_resolution_port
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.resource_reference.application.contracts import (
    SourceKey,
    SourceType,
    TargetKey,
    TargetType,
    reference_set_digest,
)
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    SourceReadRequest,
    canonical_payload_json,
    payload_digest,
)
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository


def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _invalid(reason="app_reference_source_invalid"):
    return ResourceReferenceInvalidError(reason=reason)


class HostedAppReferenceSourceOwner:
    def __init__(self, repository=None, authorization_context=None):
        self.repository = repository if repository is not None else HostedAppReferenceSourceRepository()
        self.authorization_context = authorization_context
        self.references = ReferenceRepository()
        self._plans = object()

    async def _management_context(self, session, root, version, identity, *, for_update):
        context = self.authorization_context
        actor = await resolve_app_actor(identity)
        if (
            context.get("target") != {"tenant_id": root["tenant_id"], "app_id": root["id"], "version_id": version["id"]}
            or context.get("actor")
            != {"subject_type": actor.subject_type, "subject_id": actor.subject_id, "tenant_id": actor.tenant_id}
            or context.get("schema") != 1
            or context.get("origin_kind") != "user_request"
        ):
            raise _invalid("app_management_source_context")
        if isinstance(identity, OpenApiPrincipal):
            facts = await self.repository.aget_runtime_identity(
                session, root, identity.credential_id, for_update=for_update
            )
            credential = facts["credential"]
            now = datetime.utcnow()
            if (
                credential is None
                or credential["revoked_at"] is not None
                or (credential["expires_at"] is not None and credential["expires_at"] <= now)
                or (credential["tenant_id"], credential["subject_kind"], credential["subject_id"])
                != (identity.tenant_id, identity.actor_kind, identity.actor_id)
                or frozenset(credential["scopes"] or ()) != identity.scopes
            ):
                raise OpenApiCredentialInvalidError()
        elif context.get("credential_ref") != identity._runtime_credential_reference:
            raise _invalid("app_management_source_credential")
        await authorize_loaded_app(
            identity, SimpleNamespace(**root), context.get("purpose"), resume=context.get("resume_after_restore", False)
        )

    async def _qualification(self, session, root, version, identity, qualification, *, viewer_id, for_update):
        q = qualification
        if not isinstance(q, PreviewQualification) or (q.tenant_id, q.app_id, q.version_id, q.viewer_user_id) != (
            root["tenant_id"],
            root["id"],
            version["id"],
            viewer_id,
        ):
            raise _invalid("app_preview_qualification_invalid")
        if q.purpose == "management":
            await authorize_loaded_app(identity, SimpleNamespace(**root), "management_preview")
            return viewer_id
        if q.purpose != "approval" or version["terminal_state"]:
            raise _invalid("app_preview_qualification_invalid")
        grants = await pending_app_reviews(
            viewer_id, root["id"], {version["id"]}, session=session, for_update=for_update
        )
        if len(grants) != 1 or (
            grants[0].tenant_id,
            grants[0].version_id,
            grants[0].instance_id,
            grants[0].task_id,
        ) != (q.tenant_id, q.version_id, q.approval_instance_id, q.approval_task_id):
            raise _invalid("app_preview_pending_task_required")
        return root["owner_user_id"]

    async def _principal(self, session, root, request, identity, *, for_update):
        await AppSourceReadIdentity().acapture(identity)
        if identity.subject_ref != root["id"]:
            raise _invalid("app_reference_principal_root")
        facts = await self.repository.aget_runtime_identity(
            session, root, identity.credential_id, for_update=for_update
        )
        credential, subject = facts["credential"], facts["subject"]
        now = datetime.utcnow()
        if (
            credential is None
            or subject is None
            or (
                credential["tenant_id"],
                credential["subject_kind"],
                credential["subject_id"],
                subject["id"],
                subject["app_id"],
            )
            != (root["tenant_id"], "hosted_app", identity.actor_id, identity.actor_id, root["id"])
            or credential["revoked_at"] is not None
            or (credential["expires_at"] is not None and credential["expires_at"] <= now)
            or frozenset(credential["scopes"] or ()) != identity.scopes
            or identity.resource_owner_user_id != root["owner_user_id"]
            or identity.authorization_subject_type != "user"
            or identity.effective_user_id is not None
        ):
            raise OpenApiCredentialInvalidError()
        if identity.preview_session_id:
            preview, op = facts["preview"], facts["operation"]
            if (
                preview is None
                or op is None
                or preview["status"] != "running"
                or preview["expires_at"] <= now
                or (preview["id"], preview["version_id"], preview["purpose"], preview["approver_user_id"])
                != (
                    identity.preview_session_id,
                    identity.preview_version_id,
                    identity.preview_purpose,
                    identity.preview_viewer_user_id,
                )
                or request.source_version not in {None, preview["version_id"]}
                or not identity.preview_obo_expires_at
                or identity.preview_obo_expires_at <= time.time()
                or (op["id"], op["app_id"], op["tenant_id"], op["version_id"], op["kind"])
                != (preview["operation_id"], root["id"], root["tenant_id"], preview["version_id"], "preview")
                or op["status"] in {"completed", "failed", "cancelled", "timed_out"}
                or op["deadline"] <= now
                or op["payload"].get("cancel_requested")
            ):
                raise OpenApiCredentialInvalidError()
            auth = op["payload"].get("authorization_context") or {}
            route = facts["preview_route"]
            if (
                (
                    op["payload"].get("session_id"),
                    op["payload"].get("preview_purpose"),
                    op["payload"].get("preview_credential_id"),
                )
                != (preview["id"], preview["purpose"], credential["id"])
                or auth.get("purpose")
                != ("management_preview" if preview["purpose"] == "management" else "approval_preview")
                or (auth.get("actor") or {}).get("subject_id") != preview["approver_user_id"]
                or (
                    preview["purpose"] == "approval"
                    and (auth.get("approval_instance_id"), auth.get("approval_task_id"))
                    != (preview["approval_instance_id"], preview["approval_task_id"])
                )
                or route is None
                or route["status"] != "serving"
                or (route["operation_id"], route["version_id"], route["generation"], route["owner_epoch"])
                != (op["id"], op["version_id"], op["generation"], op["owner_epoch"])
            ):
                raise OpenApiCredentialInvalidError()
            return preview["version_id"], preview
        if (
            facts["preview"] is not None
            or root["state"] != "online"
            or not root["current_version_id"]
            or request.source_version not in {None, root["current_version_id"]}
            or identity.authorization_subject_id != root["owner_user_id"]
            or any(
                (
                    identity.preview_version_id,
                    identity.preview_purpose,
                    identity.preview_viewer_user_id,
                    identity.preview_capability_user_id,
                    identity.preview_obo_expires_at,
                )
            )
        ):
            raise OpenApiCredentialInvalidError()
        if settings.app_runtime.runtime_protocol_version == 2:
            route, binding = facts["route"], facts["binding"]
            if route is None:
                valid = binding is None
            else:
                valid = bool(
                    binding
                    and binding["state"] == "active"
                    and route["status"] == "serving"
                    and binding["operation_id"] == route["operation_id"]
                    and binding["version_id"] == route["version_id"] == root["current_version_id"]
                )
            if not valid:
                raise OpenApiCredentialInvalidError()
        return root["current_version_id"], None

    async def _frozen(self, session, root, version):
        key = SourceKey(root["tenant_id"], SourceType.HOSTED_APP_VERSION, root["id"], version["id"])
        with session.no_autoflush:
            source = await self.references.aget_source_set(session, key)
            raw = await self.references.alist_source_references(session, key)
        try:
            declaration = CapabilityDeclaration.model_validate(version["capabilities"])
            mapping = {row.slot_key: TargetKey(row.target_type, row.target_id) for row in raw}
            references = extract_app_references(declaration, resolved_targets=mapping)
        except (TypeError, ValueError, ValidationError) as error:
            raise ReferenceCoverageNotReadyError(reason="app_source_configuration_drift") from error
        if (
            source is None
            or not source.ready
            or source.extractor_version != APP_REFERENCE_EXTRACTOR_VERSION
            or len(raw) != len(mapping)
            or source.digest != reference_set_digest(references)
            or any(row.source_revision != source.source_revision for row in raw)
        ):
            raise ReferenceCoverageNotReadyError(reason="app_source_not_indexed")
        return key, declaration, references

    async def _load(self, session, request, identity, *, for_update, prepared=None):
        if (
            not isinstance(request, SourceReadRequest)
            or request.source_type != SourceType.HOSTED_APP_VERSION
            or request.inspect_token is not None
            or not isinstance(identity, (UserPayload, OpenApiPrincipal))
        ):
            raise _invalid()
        # Consume only the original target/name plan before taking the business root.
        if prepared is not None and prepared[1] is not None:
            old = prepared[0]
            await resolve_app_references(
                session,
                CapabilityDeclaration.model_validate(json.loads(old.payload_json)["capabilities"]),
                identity=identity,
                source_tenant_id=old.source_key.tenant_id,
                model_name_plan=prepared[1],
                frozen_references=old.references,
            )
        root = await self.repository.aget_root(session, request.source_id, for_update=for_update)
        preview = None
        hosted = isinstance(identity, OpenApiPrincipal) and identity.actor_kind == "hosted_app"
        if hosted:
            version_id, preview = await self._principal(session, root, request, identity, for_update=for_update)
        else:
            await AppManagementSourceReadIdentity(self.authorization_context).acapture(identity)
            context_version = (
                (self.authorization_context.get("target") or {}).get("version_id")
                if isinstance(self.authorization_context, dict)
                else None
            )
            if context_version and request.source_version not in {None, context_version}:
                raise _invalid("app_management_source_version")
            version_id = request.source_version or context_version or root["current_version_id"]
        if not version_id:
            raise _invalid("app_source_version_required")
        version = await self.repository.aget_version(session, root, version_id, for_update=for_update)
        if version is None:
            raise AppNotFoundError()
        if not hosted:
            if isinstance(self.authorization_context, dict):
                await self._management_context(session, root, version, identity, for_update=for_update)
            elif self.authorization_context is not None:
                await self._qualification(
                    session,
                    root,
                    version,
                    identity,
                    self.authorization_context,
                    viewer_id=identity.user_id,
                    for_update=for_update,
                )
            elif request.purpose == "execute" and version["id"] == root["current_version_id"]:
                await require_business_action(identity, resource_type="app", resource_id=root["id"], action="visible")
            else:
                await authorize_loaded_app(
                    identity,
                    SimpleNamespace(**root),
                    "management_read" if request.purpose == "inspect" else "management_preview",
                )
        elif preview is not None:
            qualification = PreviewQualification(
                root["tenant_id"],
                root["id"],
                version_id,
                preview["approver_user_id"],
                preview["purpose"],
                preview["approval_instance_id"],
                preview["approval_task_id"],
            )
            ceiling = await self._qualification(
                session,
                root,
                version,
                identity,
                qualification,
                viewer_id=preview["approver_user_id"],
                for_update=for_update,
            )
            if identity.authorization_subject_id != ceiling or identity.preview_capability_user_id != ceiling:
                raise OpenApiCredentialInvalidError()
        key, declaration, references = await self._frozen(session, root, version)
        plan = prepared[1] if prepared is not None else None
        if request.purpose == "execute" and prepared is None:
            names = get_model_name_resolution_port()
            frozen = await names.aresolve_frozen_model_identities(
                session,
                root["tenant_id"],
                tuple(
                    sorted(
                        {
                            int(item.target.target_id)
                            for item in references
                            if item.target.target_type == TargetType.MODEL
                        }
                    )
                ),
                identity=identity,
            )
            requested = tuple(
                sorted(
                    {
                        item.requested_name
                        for item in extract_app_reference_requests(declaration)
                        if item.target_type == TargetType.MODEL
                    }
                )
            )
            plan = await names.aprepare_model_names_current(
                session, root["tenant_id"], requested, identity=identity, frozen_models=frozen
            )
            await resolve_app_references(
                session,
                declaration,
                identity=identity,
                source_tenant_id=root["tenant_id"],
                model_name_plan=plan,
                frozen_references=references,
            )
        payload = canonical_payload_json(
            _json_value(
                {
                    "root": root,
                    "version": {
                        key: value
                        for key, value in version.items()
                        if key not in {"manifest", "capabilities", "injections"}
                    },
                    "manifest": version["manifest"],
                    "capabilities": version["capabilities"],
                }
            )
        )
        snapshot = AuthorizedSourceSnapshot(
            key, references, APP_REFERENCE_EXTRACTOR_VERSION, payload_digest(payload), payload
        )
        if prepared is None:
            session.info.setdefault(self._plans, {})[id(snapshot)] = (snapshot, plan, identity, request)
        return snapshot

    async def aresolve_source(self, session, request, identity):
        return await self._load(session, request, identity, for_update=False)

    async def arevalidate_source(self, session, request, identity, expected):
        registered = session.info.get(self._plans, {}).get(id(expected))
        if (
            registered is None
            or registered[0] is not expected
            or registered[2] is not identity
            or registered[3] != request
        ):
            raise _invalid("app_source_snapshot_invalid")
        try:
            current = await self._load(session, request, identity, for_update=True, prepared=registered)
        except AppNotFoundError as error:
            raise KnowledgeOperationPlanConflictError(reason="app_source_changed") from error
        if current != expected:
            raise KnowledgeOperationPlanConflictError(reason="app_source_changed")
        return current
