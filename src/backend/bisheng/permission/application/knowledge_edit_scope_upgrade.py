"""Explicit file/folder edit scope upgrade through the existing Catalog publisher.

Only two resource/action pairs are added. No Grant, assignee, mode, model
selection, or authorization-model schema is rewritten by this maintenance path.
"""

from dataclasses import asdict, replace
from datetime import timedelta

from loguru import logger

from bisheng.common.errcode.permission import (
    PermissionImpactExpiredError,
    PermissionPublishNotReadyError,
    PermissionVersionConflictError,
)
from bisheng.permission.application.catalog_api import ZERO_CHECKSUM, SqlCatalogImpact, SqlCatalogState, _utc_now_naive
from bisheng.permission.application.control_state import SqlPermissionControlState
from bisheng.permission.domain.services.catalog_policy import calculate_action_impact, derive_action_release
from bisheng.permission.domain.services.catalog_service import CatalogDraftBuildInput, CatalogService, _checksum
from bisheng.permission.domain.services.model_policy import (
    CustomModelSelection,
    calculate_model_impact,
    derive_permission_models,
)

UPGRADE_KEY = "file-folder-edit-v1:"
EDIT_TYPES = frozenset({"folder", "knowledge_file"})


def publication_key(key: str) -> str:
    if not isinstance(key, str) or not key.strip() or len(key) > 128:
        raise ValueError("A non-empty idempotency key of at most 128 characters is required")
    return UPGRADE_KEY + _checksum(key)[:32]


def _selection(snapshot):
    customs = tuple(
        CustomModelSelection(
            model_key=model.model_key,
            name=model.name,
            action_codes=model.selected_action_codes,
            active=model.active,
            allow_same_level=model.allow_same_level,
            config_scope=model.config_scope,
            visibility_only_resource_types=model.visibility_only_resource_types,
            visibility_level=model.visibility_level,
            retired_use_level_floor=model.retired_use_level_floor,
        )
        for model in snapshot.model_release.models
        if model.kind == "CUSTOM"
    )
    standard_policy = {
        model.model_key: model.allow_same_level for model in snapshot.model_release.models if model.kind == "STANDARD"
    }
    return customs, standard_policy


def _target(snapshot):
    if snapshot.action_release is None or snapshot.model_release is None:
        raise PermissionPublishNotReadyError(msg="Complete Catalog payload is required")
    actions = derive_action_release(
        replace(action, resource_types=action.resource_types | EDIT_TYPES) if action.code == "edit" else action
        for action in snapshot.action_release.actions
    )
    customs, standard_policy = _selection(snapshot)
    models = derive_permission_models(actions, custom_models=customs, standard_allow_same_level=standard_policy)
    if models.blockers:
        raise PermissionPublishNotReadyError(msg="Catalog models are blocked: " + ", ".join(models.blockers))
    return actions, models, customs, standard_policy


class KnowledgeEditScopeUpgrade:
    def __init__(self, *, state: SqlCatalogState, projector):
        self.state, self.projector = state, projector
        self.impact = SqlCatalogImpact(session_factory=state._session_factory)
        self.service = CatalogService(state=state, impact=self.impact, projector=projector)
        self.control = SqlPermissionControlState(session_factory=state._session_factory)

    async def plan(self):
        """Read-only: bind the complete baseline and current impact to a digest."""
        current = await self.control.current_catalog()
        before = await self.state.load_snapshot(current.release_id)
        actions, models, _, _ = _target(before)
        edit = next(action for action in before.action_release.actions if action.code == "edit")
        missing = tuple(sorted(EDIT_TYPES - edit.resource_types))
        action_impact = calculate_action_impact(
            before.action_release,
            actions,
            custom_model_actions={
                model.model_key: frozenset(model.selected_action_codes)
                for model in before.model_release.models
                if model.kind == "CUSTOM"
            },
        )
        impact = await self.impact.analyze_draft(
            action_impact=action_impact,
            model_impact=calculate_model_impact(before.model_release, models, grant_references={}),
            before_actions=before.action_release,
            after_actions=actions,
            before_models=before.model_release,
            after_models=models,
        )
        payload = {
            "upgrade": UPGRADE_KEY,
            "base_release_id": current.release_id,
            "base_checksum": current.checksum,
            "store_id": current.store_id,
            "model_id": current.model_id,
            "model_checksum": current.model_checksum,
            "action_checksum": actions.checksum,
            "model_selection_checksum": models.checksum,
            "impact_checksum": impact.checksum,
        }
        return {
            "event": "noop" if not missing else "plan",
            **payload,
            "missing_scopes": [["edit", kind] for kind in missing],
            "edit_active": edit.active,
            "edit_level": edit.level,
            "impact": asdict(impact),
            "plan_digest": _checksum(payload),
        }

    async def apply(self, *, plan_digest: str, operator_id: int, idempotency_key: str):
        if type(operator_id) is not int or operator_id <= 0:
            raise ValueError("A positive audit operator ID is required")
        key = publication_key(idempotency_key)
        existing = await self.state.release_for_idempotency(key)
        if existing is not None and existing.draft_owner_id != operator_id:
            raise PermissionVersionConflictError(msg="Upgrade operator differs from the reserved operation")
        if existing is not None and existing.checksum != ZERO_CHECKSUM:
            return await self.resume(draft_id=existing.id, operator_id=operator_id, idempotency_key=idempotency_key)
        plan = await self.plan()
        if plan["event"] == "noop":
            return await self.verify()
        if plan_digest != plan["plan_digest"]:
            raise PermissionVersionConflictError(msg="Catalog or upgrade impact changed; run plan again")
        reservation = await self.state.reserve_draft(
            base_release_id=plan["base_release_id"],
            operator_id=operator_id,
            idempotency_key=key,
            expires_at=_utc_now_naive() + timedelta(minutes=10),
        )
        logger.info("File/folder edit upgrade reserved Catalog draft_id={}", reservation.release_id)
        if not reservation.complete:
            before = await self.state.load_snapshot(reservation.predecessor_id)
            if before.release_checksum != plan["base_checksum"]:
                raise PermissionVersionConflictError(msg="Catalog baseline changed during reservation")
            actions, _, customs, policy = _target(before)
            draft = await self.service.build_draft(
                CatalogDraftBuildInput(
                    release_id=reservation.release_id,
                    release_key=reservation.release_key,
                    predecessor_release_id=reservation.predecessor_id,
                    predecessor_release_key=reservation.predecessor_key,
                    before_actions=before.action_release,
                    before_models=before.model_release,
                    actions=actions.actions,
                    custom_models=customs,
                    standard_allow_same_level=policy,
                    draft_owner_id=operator_id,
                    idempotency_key=key,
                    expires_at=_utc_now_naive() + timedelta(minutes=10),
                )
            )
            if draft.impact_checksum != plan["impact_checksum"]:
                raise PermissionImpactExpiredError(msg="Upgrade impact changed before publication")
        return await self.resume(
            draft_id=reservation.release_id, operator_id=operator_id, idempotency_key=idempotency_key
        )

    async def resume(self, *, draft_id: int, operator_id: int, idempotency_key: str):
        """Resume only this operation; never commit a partially staged release."""
        row = await self.state.release_row(draft_id)
        if row.idempotency_key != publication_key(idempotency_key) or row.draft_owner_id != operator_id:
            raise PermissionVersionConflictError(msg="Upgrade draft belongs to another operation or operator")
        draft = await self.state.load_snapshot(draft_id)
        before = await self.state.load_snapshot(draft.predecessor_release_id)
        actions, models, _, _ = _target(before)
        if draft.action_release != actions or draft.model_release != models:
            raise PermissionVersionConflictError(msg="Upgrade draft changes more than file/folder edit applicability")
        current = await self.state.current_release()
        if current.id == draft_id and row.status == "CURRENT":
            return await self.verify()
        if current.id != draft.predecessor_release_id:
            raise PermissionVersionConflictError(msg="Upgrade predecessor is no longer CURRENT")
        active = await self.projector.read_active_release_keys()
        if active == frozenset({draft.release_key}):
            await self.service.reconcile(draft_id=draft_id)
        elif active == frozenset({before.release_key}) and row.status in {"DRAFT", "PROJECTING"}:
            # publish re-stages and verifies every tuple, including a crash
            # before staging completed. Expired drafts require a new plan/key.
            await self.service.publish(
                draft_id=draft_id,
                expected_current_release_id=draft.predecessor_release_id,
                idempotency_key=row.idempotency_key,
            )
        else:
            raise PermissionPublishNotReadyError(msg="Catalog publication requires explicit failed-closed recovery")
        return await self.verify()

    async def verify(self):
        """Check SQL integrity and the actual active OpenFGA Catalog pointer."""
        current = await self.control.current_catalog()
        snapshot = await self.state.load_snapshot(current.release_id)
        edit = next(action for action in snapshot.action_release.actions if action.code == "edit")
        # Runtime action scopes intentionally omit disabled actions; verify the
        # persisted Catalog metadata without turning an admin-disabled edit on.
        edit_scopes = edit.resource_types
        if not EDIT_TYPES <= set(edit_scopes):
            raise PermissionPublishNotReadyError(msg="File/folder edit scope upgrade is incomplete")
        if await self.projector.read_active_release_keys() != frozenset({current.release_key}):
            raise PermissionPublishNotReadyError(msg="SQL and OpenFGA Catalog pointers differ")
        await self.projector.validate_required_actions(snapshot.required_action_codes)
        await self.projector.run_model_tests(snapshot)
        return {
            "event": "verified",
            "catalog_release_id": current.release_id,
            "catalog_checksum": current.checksum,
            "store_id": current.store_id,
            "model_id": current.model_id,
            "edit_scopes": sorted(edit_scopes),
            "edit_active": edit.active,
            "edit_level": edit.level,
        }
