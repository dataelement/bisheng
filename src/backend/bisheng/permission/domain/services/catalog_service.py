"""F048 Catalog draft and atomic publication orchestration.

The service depends only on narrow ports. SQL locking/transactions and OpenFGA
HTTP are implemented by adapters outside this module.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from typing import Protocol

from loguru import logger

from bisheng.common.errcode.permission import (
    AuthorizationModelMismatchError,
    PermissionImpactExpiredError,
    PermissionModelStateConflictError,
    PermissionProjectionFailedError,
    PermissionPublishNotReadyError,
)
from bisheng.permission.domain.services.catalog_policy import (
    CatalogAction,
    CatalogActionImpact,
    CatalogActionRelease,
    calculate_action_impact,
    derive_action_release,
)
from bisheng.permission.domain.services.model_policy import (
    CustomModelSelection,
    ModelReferenceSummary,
    PermissionModelImpact,
    PermissionModelRelease,
    calculate_model_impact,
    derive_permission_models,
    ensure_model_deletable,
)


class CatalogCommitUnknownError(RuntimeError):
    """The active-pointer write may or may not have reached OpenFGA."""


@dataclass(frozen=True, slots=True)
class CatalogImpactSummary:
    """Cross-tenant impact aggregate bound to one complete draft."""

    checksum: str
    resource_count: int
    grant_count: int
    assignee_count: int
    expansion_count: int
    revocation_count: int
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CatalogDraftBuildInput:
    """Complete inputs needed to rebuild a Catalog draft."""

    release_id: int
    release_key: str
    predecessor_release_id: int
    predecessor_release_key: str
    before_actions: CatalogActionRelease
    before_models: PermissionModelRelease
    actions: tuple[CatalogAction, ...]
    custom_models: tuple[CustomModelSelection, ...] = ()
    standard_allow_same_level: Mapping[str, bool] = field(default_factory=dict)
    grant_references: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    model_reference_summaries: Mapping[str, ModelReferenceSummary] = field(default_factory=dict)
    draft_owner_id: int = 0
    idempotency_key: str = ""
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CatalogDraftSnapshot:
    """Durable, self-contained publication input."""

    release_id: int
    release_key: str
    predecessor_release_id: int
    predecessor_release_key: str
    release_checksum: str
    impact_checksum: str
    required_action_codes: tuple[str, ...]
    blockers: tuple[str, ...]
    action_release: CatalogActionRelease | None = None
    model_release: PermissionModelRelease | None = None
    impact: CatalogImpactSummary | None = None
    draft_owner_id: int = 0
    idempotency_key: str = ""
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CatalogPublishContext:
    """State returned while the current release is locked and fenced."""

    draft: CatalogDraftSnapshot
    current_release_id: int
    current_release_key: str
    status: str
    already_current: bool = False


@dataclass(frozen=True, slots=True)
class CatalogTupleChange:
    """One member of the two-tuple active-pointer commit."""

    action: str
    user: str
    relation: str
    object: str


@dataclass(frozen=True, slots=True)
class CatalogPublishOutcome:
    release_id: int
    release_key: str
    status: str
    release_checksum: str
    idempotent: bool = False
    reconciled: bool = False


class CatalogStatePort(Protocol):
    async def save_draft(
        self,
        draft: CatalogDraftSnapshot,
    ) -> CatalogDraftSnapshot: ...

    async def prepare_publish(
        self,
        *,
        draft_id: int,
        expected_current_release_id: int,
        idempotency_key: str,
    ) -> CatalogPublishContext: ...

    async def mark_projecting(self, context: CatalogPublishContext) -> None: ...

    async def mark_committed(
        self,
        context: CatalogPublishContext,
        *,
        commit_checksum: str,
    ) -> None: ...

    async def finalize_publish(self, context: CatalogPublishContext) -> None: ...

    async def abort_before_commit(
        self,
        context: CatalogPublishContext,
        *,
        reason: str,
    ) -> None: ...

    async def fail_closed(
        self,
        context: CatalogPublishContext,
        *,
        reason: str,
    ) -> None: ...

    async def get_publish_context(
        self,
        draft_id: int,
    ) -> CatalogPublishContext: ...


class CatalogImpactPort(Protocol):
    async def analyze_draft(
        self,
        *,
        action_impact: CatalogActionImpact,
        model_impact: PermissionModelImpact,
        before_actions: CatalogActionRelease,
        after_actions: CatalogActionRelease,
        before_models: PermissionModelRelease,
        after_models: PermissionModelRelease,
    ) -> CatalogImpactSummary: ...

    async def recalculate(self, draft: CatalogDraftSnapshot) -> str: ...


class CatalogProjectorPort(Protocol):
    async def validate_required_actions(
        self,
        action_codes: tuple[str, ...],
    ) -> None: ...

    async def stage_model_releases(
        self,
        draft: CatalogDraftSnapshot,
    ) -> None: ...

    async def run_model_tests(self, draft: CatalogDraftSnapshot) -> None: ...

    async def arm_recent_marker(self, draft: CatalogDraftSnapshot) -> None: ...

    async def commit_active(
        self,
        changes: tuple[CatalogTupleChange, CatalogTupleChange],
    ) -> str: ...

    async def read_active_release_keys(self) -> frozenset[str]: ...


class CatalogEventPort(Protocol):
    async def record_audit(self, event: str, fields: dict) -> None: ...

    async def emit_metric(self, event: str, fields: dict) -> None: ...


class _NullCatalogEvents:
    async def record_audit(self, event: str, fields: dict) -> None:
        return None

    async def emit_metric(self, event: str, fields: dict) -> None:
        return None


def _checksum(payload: object) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


class CatalogService:
    """Build complete releases and publish them behind one global pointer."""

    def __init__(
        self,
        *,
        state: CatalogStatePort,
        impact: CatalogImpactPort,
        projector: CatalogProjectorPort,
        events: CatalogEventPort | None = None,
    ) -> None:
        self._state = state
        self._impact = impact
        self._projector = projector
        self._events = events or _NullCatalogEvents()

    async def build_draft(
        self,
        build: CatalogDraftBuildInput,
    ) -> CatalogDraftSnapshot:
        """Rebuild all models and persist one complete impact-bound draft."""

        action_release = derive_action_release(build.actions)
        model_release = derive_permission_models(
            action_release,
            custom_models=build.custom_models,
            standard_allow_same_level=build.standard_allow_same_level,
        )
        before_by_key = {model.model_key: model for model in build.before_models.models}
        after_keys = {model.model_key for model in model_release.models}
        deleted_models = tuple(
            before_by_key[model_key]
            for model_key in sorted(set(before_by_key) - after_keys)
        )
        for model in deleted_models:
            references = build.model_reference_summaries.get(model.model_key)
            if references is None:
                raise PermissionModelStateConflictError(
                    msg=f"Model reference audit is missing: {model.model_key}"
                )
            try:
                ensure_model_deletable(model, references=references)
            except ValueError as exc:
                raise PermissionModelStateConflictError(
                    exception=exc,
                    msg=str(exc),
                ) from exc
        custom_action_map = {
            model.model_key: frozenset(model.selected_action_codes)
            for model in build.before_models.models
            if model.kind == "CUSTOM"
        }
        custom_action_map.update({model.model_key: frozenset(model.action_codes) for model in build.custom_models})
        action_impact = calculate_action_impact(
            build.before_actions,
            action_release,
            custom_model_actions=custom_action_map,
        )
        model_impact = calculate_model_impact(
            build.before_models,
            model_release,
            grant_references=build.grant_references,
        )
        impact = await self._impact.analyze_draft(
            action_impact=action_impact,
            model_impact=model_impact,
            before_actions=build.before_actions,
            after_actions=action_release,
            before_models=build.before_models,
            after_models=model_release,
        )
        blockers = tuple(sorted(set(model_release.blockers) | set(impact.blockers)))
        release_checksum = _checksum(
            {
                "actions": action_release.checksum,
                "models": model_release.checksum,
                "predecessor_release_id": build.predecessor_release_id,
                "release_key": build.release_key,
            }
        )
        draft = CatalogDraftSnapshot(
            release_id=build.release_id,
            release_key=build.release_key,
            predecessor_release_id=build.predecessor_release_id,
            predecessor_release_key=build.predecessor_release_key,
            release_checksum=release_checksum,
            impact_checksum=impact.checksum,
            required_action_codes=tuple(action.code for action in action_release.actions),
            blockers=blockers,
            action_release=action_release,
            model_release=model_release,
            impact=impact,
            draft_owner_id=build.draft_owner_id,
            idempotency_key=build.idempotency_key,
            expires_at=build.expires_at,
        )
        return await self._state.save_draft(draft)

    async def publish(
        self,
        *,
        draft_id: int,
        expected_current_release_id: int,
        idempotency_key: str,
    ) -> CatalogPublishOutcome:
        """Fence writes, stage the release, and atomically switch two tuples."""

        context = await self._state.prepare_publish(
            draft_id=draft_id,
            expected_current_release_id=expected_current_release_id,
            idempotency_key=idempotency_key,
        )
        if context.already_current:
            return self._outcome(context, idempotent=True)
        if context.status == "COMMITTED":
            return await self._resolve_unknown_commit(
                context,
                original_error=CatalogCommitUnknownError("resuming committed Catalog publication"),
                allow_retry=False,
            )

        try:
            self._ensure_publishable(context.draft)
            await self._ensure_impact_current(context.draft)
            await self._projector.validate_required_actions(context.draft.required_action_codes)
            await self._state.mark_projecting(context)
            await self._projector.stage_model_releases(context.draft)
            await self._projector.run_model_tests(context.draft)
            await self._ensure_impact_current(context.draft)
            await self._projector.arm_recent_marker(context.draft)
        except (
            AuthorizationModelMismatchError,
            PermissionImpactExpiredError,
            PermissionPublishNotReadyError,
        ) as exc:
            await self._abort(context, exc)
            raise
        except Exception as exc:
            await self._abort(context, exc)
            raise PermissionProjectionFailedError(exception=exc) from exc

        changes = self._active_pointer_changes(context)
        try:
            commit_checksum = await self._projector.commit_active(changes)
        except Exception as exc:
            return await self._resolve_unknown_commit(
                context,
                original_error=exc,
                allow_retry=True,
            )

        return await self._finish_committed(
            context,
            commit_checksum=commit_checksum,
            reconciled=False,
        )

    async def reconcile(self, *, draft_id: int) -> CatalogPublishOutcome:
        """Recover a fenced publication using higher-consistency active reads."""

        context = await self._state.get_publish_context(draft_id)
        if context.already_current:
            return self._outcome(context, idempotent=True, reconciled=True)
        return await self._resolve_unknown_commit(
            context,
            original_error=CatalogCommitUnknownError("reconciling non-final Catalog publication"),
            allow_retry=context.status in {"PROJECTING", "COMMIT_UNKNOWN"},
        )

    @staticmethod
    def _ensure_publishable(draft: CatalogDraftSnapshot) -> None:
        if draft.blockers:
            raise PermissionPublishNotReadyError(msg=f"Catalog draft has blockers: {', '.join(draft.blockers)}")

    async def _ensure_impact_current(
        self,
        draft: CatalogDraftSnapshot,
    ) -> None:
        current_checksum = await self._impact.recalculate(draft)
        if current_checksum != draft.impact_checksum:
            raise PermissionImpactExpiredError(msg="Catalog impact checksum changed before publication")

    @staticmethod
    def _active_pointer_changes(
        context: CatalogPublishContext,
    ) -> tuple[CatalogTupleChange, CatalogTupleChange]:
        return (
            CatalogTupleChange(
                action="DELETE",
                user="user:*",
                relation="active",
                object=(f"permission_catalog_release:{context.current_release_key}"),
            ),
            CatalogTupleChange(
                action="WRITE",
                user="user:*",
                relation="active",
                object=f"permission_catalog_release:{context.draft.release_key}",
            ),
        )

    async def _abort(
        self,
        context: CatalogPublishContext,
        error: Exception,
    ) -> None:
        try:
            await self._state.abort_before_commit(
                context,
                reason=str(error),
            )
        except Exception as abort_error:
            await self._state.fail_closed(
                context,
                reason=f"precommit abort failed: {abort_error}",
            )
        await self._emit(context, status="ABORTED", error=error)

    async def _resolve_unknown_commit(
        self,
        context: CatalogPublishContext,
        *,
        original_error: Exception,
        allow_retry: bool,
    ) -> CatalogPublishOutcome:
        try:
            active = await self._projector.read_active_release_keys()
        except Exception as exc:
            # Reading the pointer is how this path tells "committed" from "never
            # committed". If that read itself fails the publication is
            # unresolvable, so land it in the fenced terminal state instead of
            # letting the error escape — an escaping error leaves the CURRENT
            # release fenced with no FAILED_CLOSED marker and no event, which is
            # invisible until a restart takes the whole permission runtime down.
            return await self._fail_closed(
                context,
                reason=(
                    f"Catalog active pointer is unreadable after commit: error={exc}, original_error={original_error}"
                ),
            )
        old_key = context.current_release_key
        new_key = context.draft.release_key

        if active == {new_key}:
            return await self._finish_committed(
                context,
                commit_checksum=context.draft.release_checksum,
                reconciled=True,
            )

        if active == {old_key} and allow_retry:
            try:
                await self._projector.arm_recent_marker(context.draft)
                commit_checksum = await self._projector.commit_active(self._active_pointer_changes(context))
            except Exception:
                active = await self._projector.read_active_release_keys()
                if active == {new_key}:
                    return await self._finish_committed(
                        context,
                        commit_checksum=context.draft.release_checksum,
                        reconciled=True,
                    )
            else:
                return await self._finish_committed(
                    context,
                    commit_checksum=commit_checksum,
                    reconciled=True,
                )

        await self._fail_closed(
            context,
            reason=(
                f"Catalog active pointer invariant violated after commit: "
                f"active={sorted(active)}, error={original_error}"
            ),
        )

    async def _fail_closed(
        self,
        context: CatalogPublishContext,
        *,
        reason: str,
    ) -> CatalogPublishOutcome:
        """Record the fenced terminal state, then raise.

        Publishing fences the CURRENT release and only a resolved commit lifts
        that fence, so an unresolvable publication is meant to stay fenced. What
        it must never do is stay fenced *unlabelled*: the release has to end up
        FAILED_CLOSED with a reason, or the next process restart refuses to serve
        permissions with nothing on record explaining why.
        """

        await self._state.fail_closed(context, reason=reason)
        await self._emit(
            context,
            status="FAILED_CLOSED",
            error=PermissionProjectionFailedError(msg=reason),
        )
        raise PermissionProjectionFailedError(msg=reason)

    async def _finish_committed(
        self,
        context: CatalogPublishContext,
        *,
        commit_checksum: str,
        reconciled: bool,
    ) -> CatalogPublishOutcome:
        try:
            if context.status != "COMMITTED":
                await self._state.mark_committed(
                    context,
                    commit_checksum=commit_checksum,
                )
            await self._state.finalize_publish(context)
        except Exception as exc:
            await self._emit(context, status="COMMITTED_NOT_FINALIZED", error=exc)
            raise PermissionProjectionFailedError(exception=exc) from exc
        await self._emit(context, status="CURRENT")
        return self._outcome(context, reconciled=reconciled)

    async def _emit(
        self,
        context: CatalogPublishContext,
        *,
        status: str,
        error: Exception | None = None,
    ) -> None:
        fields = {
            "release_id": context.draft.release_id,
            "release_key": context.draft.release_key,
            "status": status,
            "checksum": context.draft.release_checksum,
        }
        if error is not None:
            fields["error"] = type(error).__name__
        try:
            await self._events.record_audit(
                "permission_catalog_publish",
                fields,
            )
            await self._events.emit_metric(
                "permission_catalog_publish",
                fields,
            )
        except Exception:
            # Observability must not change a confirmed authorization outcome.
            logger.exception("Failed to emit the F048 Catalog publish event")
            return

    @staticmethod
    def _outcome(
        context: CatalogPublishContext,
        *,
        idempotent: bool = False,
        reconciled: bool = False,
    ) -> CatalogPublishOutcome:
        return CatalogPublishOutcome(
            release_id=context.draft.release_id,
            release_key=context.draft.release_key,
            status="CURRENT",
            release_checksum=context.draft.release_checksum,
            idempotent=idempotent,
            reconciled=reconciled,
        )
