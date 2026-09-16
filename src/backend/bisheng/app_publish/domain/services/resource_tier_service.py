"""Resource tiers: seed, selection, retirement and usage counting (F055 design D11).

The table (``database/models/resource_tier.py``) is deliberately dumb — every
rule about tiers lives here, and there are only four of them:

* **The factory specs come from F054's ``DEFAULT_TIERS``**, overridable by
  ``settings.app_runtime.default_tiers``. Neither this module nor the table
  holds a second literal copy: an un-seeded deployment resolves its limits from
  the constant and a seeded one from the DB, and the two must agree or
  ``docker inspect`` will disagree with the admin page (design 坑 27).
* **Seeding is idempotent by ``code``** — a tier a super admin retuned is never
  reset by a later upgrade (same judgement as AC-19). An override in deployment
  configuration therefore only affects a deployment that has not been seeded
  yet, which is exactly why 114 has to set it *before* the first boot.
* **Selecting and resolving are different questions.** :meth:`resolve_tier` is
  "may a new publish choose this?" and rejects a retired tier;
  :meth:`resolve_spec` is "what does this frozen ``tier_id`` mean?" and answers
  for retired tiers too. AC-47 is the difference between the two: retiring a
  tier must not stop the apps already on it (F054 relies on "``tier_id`` always
  resolves", which is also why the DAO has no delete).
* **A tier failure is exactly one error code.** ``16223`` with
  ``details.reason ∈ {not_found, disabled}``; see the errcode module docstring
  for why splitting it produced a code with no writer.

``manifest_validator`` calls :meth:`resolve_tier` rather than re-deriving the
verdict, so ``details.reason`` — which is what AC-46 / AC-47 are judged on —
has a single definition.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from bisheng.app_runtime.domain.constants import DEFAULT_TIERS, AppAuditAction
from bisheng.common.errcode.app_publish import (
    AppTierDefaultCannotBeDisabledError,
    AppTierEditTargetNotFoundError,
    AppTierSpecInvalidError,
    AppTierUnavailableError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import DEFAULT_TENANT_ID
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app_version import TERMINAL_STATE_ONLINE, AppVersion
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.resource_tier import DEFAULT_TIER_CODE, ResourceTier, ResourceTierDao

#: Order tiers are displayed in when the seed source does not say otherwise.
_SEED_ORDER = ("light", "standard", "performance")

#: Columns the admin surface may retune (AC-45). ``code`` is deliberately
#: absent — renaming a tier would dangle every ``app_version.tier_id`` frozen
#: against it — and so is ``sort_order``, which the tab does not expose.
ADMIN_EDITABLE_FIELDS = ("name", "cpu_millicores", "memory_mb", "description", "enabled")

#: ``audit_log.target_type`` of the tier admin events (``app.tier_update``).
TIER_AUDIT_TARGET_TYPE = "resource_tier"

#: Column widths of ``resource_tier`` — validated here so the failure is a
#: 16262 naming the field rather than a driver error naming a column.
_NAME_MAX_LEN = 64
_DESCRIPTION_MAX_LEN = 500
#: ``cpu_millicores`` / ``memory_mb`` are plain ``Integer`` columns (signed
#: 32-bit on both MySQL and DM8); anything above this would be a driver
#: overflow error, not a spec.
_INT_COLUMN_MAX = 2**31 - 1


def _specs_from_constant() -> dict[str, dict[str, Any]]:
    """F054's ``DEFAULT_TIERS`` (vCPU floats) in this table's shape (integer millicores).

    The unit conversion lives here and nowhere else. F054 keeps vCPU because
    that is what runtime-manager's ``tier{cpu, mem}`` payload speaks; the table
    keeps millicores because a float round-tripping through DM8 and JSON turns
    into ``0.30000000000000004`` in a super admin's edit form (design D11).
    """
    specs: dict[str, dict[str, Any]] = {}
    for index, spec in enumerate(DEFAULT_TIERS):
        code = str(spec["tier_id"])
        specs[code] = {
            "name": str(spec["name"]),
            "cpu_millicores": round(float(spec["cpu"]) * 1000),
            "memory_mb": int(spec["memory_mb"]),
            "description": spec.get("description"),
            "sort_order": int(spec.get("sort_order", index)),
        }
    return specs


def _specs_from_settings() -> dict[str, dict[str, Any]] | None:
    """``settings.app_runtime.default_tiers`` normalised, or ``None`` when unset.

    Shape ``{code: {name, cpu_millicores, memory_mb, description?, sort_order?}}``.
    An override **replaces** the tier set rather than merging into it: a machine
    that only has room for two tiers should not silently get a third from the
    constant.
    """
    raw = getattr(settings.app_runtime, "default_tiers", None)
    if not raw:
        return None
    specs: dict[str, dict[str, Any]] = {}
    for index, (code, spec) in enumerate(raw.items()):
        specs[str(code)] = {
            "name": str(spec.get("name", code)),
            "cpu_millicores": int(spec["cpu_millicores"]),
            "memory_mb": int(spec["memory_mb"]),
            "description": spec.get("description"),
            "sort_order": int(spec.get("sort_order", index)),
        }
    return specs


class ResourceTierService:
    """Tier lifecycle. No delete — see the module docstring."""

    @classmethod
    def factory_specs(cls) -> dict[str, dict[str, Any]]:
        """The specs a fresh deployment would seed: deployment configuration first, constant otherwise."""
        return _specs_from_settings() or _specs_from_constant()

    @classmethod
    async def seed_resource_tiers(cls) -> list[ResourceTier]:
        """Create any missing tier; never touch one that already exists.

        Called from ``init_default_data`` at boot and directly by tests. Runs in
        its own session because it is a startup step, not part of a caller's
        unit of work.
        """
        specs = cls.factory_specs()
        created: list[ResourceTier] = []
        async with get_async_db_session() as session:
            for order, (code, spec) in enumerate(
                sorted(specs.items(), key=lambda item: (item[1].get("sort_order", 0), _rank(item[0])))
            ):
                if await ResourceTierDao.aget_by_code(session, code) is not None:
                    continue
                row = ResourceTier(
                    code=code,
                    name=spec["name"],
                    cpu_millicores=spec["cpu_millicores"],
                    memory_mb=spec["memory_mb"],
                    description=spec.get("description"),
                    enabled=True,
                    sort_order=int(spec.get("sort_order", order)),
                )
                await ResourceTierDao.acreate(session, row)
                created.append(row)
            await session.commit()
        if created:
            logger.info(f"app_publish.tier_seed created={[row.code for row in created]}")
        return created

    @classmethod
    async def list_tiers(cls, *, enabled_only: bool = False) -> list[ResourceTier]:
        """All tiers in display order; ``enabled_only`` is the list a new publish may choose from."""
        async with get_async_db_session() as session:
            return await ResourceTierDao.alist(session, enabled_only=enabled_only)

    @classmethod
    async def resolve_tier(cls, code: str | None) -> ResourceTier:
        """Resolve a manifest ``tier`` value for a **new** publish (AC-46).

        ``None`` means the manifest declared none → 轻量. Unknown or retired →
        ``16223`` carrying ``details.reason`` so the CLI can tell "you typo'd
        the tier" from "an administrator retired it".
        """
        wanted = code or DEFAULT_TIER_CODE
        async with get_async_db_session() as session:
            tier = await ResourceTierDao.aget_by_code(session, wanted)
        if tier is None:
            raise AppTierUnavailableError(
                msg=f"资源档位 {wanted} 不存在",
                details={"field": "tier", "value": wanted, "reason": "not_found"},
                hints=[f"可选档位: {', '.join(t.code for t in await cls.list_tiers(enabled_only=True))}"],
            )
        if not tier.enabled:
            raise AppTierUnavailableError(
                msg=f"资源档位 {wanted} 已停用",
                details={"field": "tier", "value": wanted, "reason": "disabled"},
                hints=[f"可选档位: {', '.join(t.code for t in await cls.list_tiers(enabled_only=True))}"],
            )
        return tier

    @classmethod
    async def resolve_spec(cls, tier_code: str) -> ResourceTier:
        """Resolve a **frozen** ``app_version.tier_id`` — retired tiers included (AC-47).

        The invariant F054 is allowed to depend on. Only a tier that never
        existed fails here, and that can only happen if somebody added a delete.
        """
        async with get_async_db_session() as session:
            tier = await ResourceTierDao.aget_by_code(session, tier_code)
        if tier is None:
            raise AppTierUnavailableError(
                msg=f"资源档位 {tier_code} 不存在",
                details={"field": "tier", "value": tier_code, "reason": "not_found"},
                hints=["历史版本引用的档位丢失: 档位只可停用不可删除, 请检查是否有人绕过 DAO 删了行"],
            )
        return tier

    @classmethod
    async def count_apps_using(cls, tier_code: str) -> int:
        """Distinct apps whose **online** version froze this tier.

        ``app_version.tier_id`` stores the tier *code* (design §4.2 ③). Only
        online versions count: a rejected or withdrawn submission never became
        somebody's running app, so warning an admin about it before retiring a
        tier would be noise.
        """
        from sqlalchemy import distinct, func
        from sqlmodel import select

        async with get_async_db_session() as session:
            result = await session.exec(
                select(func.count(distinct(AppVersion.app_id))).where(
                    AppVersion.tier_id == tier_code,
                    AppVersion.terminal_state == TERMINAL_STATE_ONLINE,
                )
            )
            return int(result.one() or 0)

    # ------------------------------------------------------------------
    # Admin surface (AC-45 / T065) — list with usage, retune, retire
    # ------------------------------------------------------------------

    @classmethod
    async def list_tiers_for_admin(cls) -> list[dict[str, Any]]:
        """Every tier — retired ones included — with its ``in_use_app_count``.

        The full list, not the selectable one: a retired tier still has apps
        on it, and the whole point of showing the count is to let a super
        admin see what a retirement (or a retune) touches.
        """
        rows = await cls.list_tiers()
        return [cls._admin_row(row, await cls.count_apps_using(row.code)) for row in rows]

    @classmethod
    async def retune_tier(cls, tier_code: str, *, actor, **patch: Any) -> dict[str, Any]:
        """Apply a super admin's inline edit to one tier and audit it (AC-45 / AC-47).

        ``patch`` holds any subset of :data:`ADMIN_EDITABLE_FIELDS`; anything
        else is a programming error, not a user error, so it raises
        ``ValueError`` the same way the DAO does. Validation is field-by-field
        with the offender in ``details.field`` (16262). Retiring the default
        tier is refused (16263) — see the error's docstring. A patch that
        changes nothing writes nothing and audits nothing, and still returns
        the current row so the tab can re-render from the answer.
        """
        unknown = set(patch) - set(ADMIN_EDITABLE_FIELDS)
        if unknown:
            raise ValueError(f"resource_tier fields not editable through the admin surface: {sorted(unknown)}")

        values = cls._validate_patch(patch)

        async with get_async_db_session() as session:
            current = await ResourceTierDao.aget_by_code(session, tier_code)
        if current is None:
            raise AppTierEditTargetNotFoundError(
                msg=f"资源档位 {tier_code} 不存在",
                details={"field": "code", "value": tier_code},
                hints=["档位列表可能已过期, 请刷新后重试"],
            )

        changes = {
            field: {"from": getattr(current, field), "to": value}
            for field, value in values.items()
            if getattr(current, field) != value
        }
        if changes.get("enabled", {}).get("to") is False and current.code == DEFAULT_TIER_CODE:
            raise AppTierDefaultCannotBeDisabledError(
                msg=f"默认资源档位 {DEFAULT_TIER_CODE} 不能停用",
                details={"field": "enabled", "value": tier_code},
                hints=["未在 bisheng-app.yaml 里声明档位的应用都会落到默认档位; 可以调整它的规格, 但不能停用"],
            )

        if changes:
            async with get_async_db_session() as session:
                await ResourceTierDao.aupdate_row(session, tier_code, **{f: c["to"] for f, c in changes.items()})
                await session.commit()
            await cls._audit_retune(current.code, actor=actor, changes=changes)

        async with get_async_db_session() as session:
            updated = await ResourceTierDao.aget_by_code(session, tier_code)
        return cls._admin_row(updated, await cls.count_apps_using(tier_code))

    @staticmethod
    def _validate_patch(patch: dict[str, Any]) -> dict[str, Any]:
        """Normalise and validate the editable fields; every failure is a 16262 naming the field."""

        def _reject(field: str, value: Any, why: str) -> AppTierSpecInvalidError:
            return AppTierSpecInvalidError(
                msg=f"资源档位字段 {field} 不合法: {why}",
                details={"field": field, "value": value, "reason": why},
            )

        values: dict[str, Any] = {}
        for field in ("cpu_millicores", "memory_mb"):
            if field not in patch:
                continue
            raw = patch[field]
            # ``bool`` is an ``int`` subclass — ``True`` must not become 1 millicore.
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise _reject(field, raw, "must_be_integer")
            if raw <= 0:
                raise _reject(field, raw, "must_be_positive")
            if raw > _INT_COLUMN_MAX:
                raise _reject(field, raw, f"max_value_{_INT_COLUMN_MAX}")
            values[field] = raw
        if "name" in patch:
            name = patch["name"].strip() if isinstance(patch["name"], str) else ""
            if not name:
                raise _reject("name", patch["name"], "must_not_be_blank")
            if len(name) > _NAME_MAX_LEN:
                raise _reject("name", patch["name"], f"max_length_{_NAME_MAX_LEN}")
            values["name"] = name
        if "description" in patch:
            description = patch["description"]
            if description is not None and not isinstance(description, str):
                raise _reject("description", description, "must_be_text")
            description = (description or "").strip() or None
            if description is not None and len(description) > _DESCRIPTION_MAX_LEN:
                raise _reject("description", patch["description"], f"max_length_{_DESCRIPTION_MAX_LEN}")
            values["description"] = description
        if "enabled" in patch:
            if not isinstance(patch["enabled"], bool):
                raise _reject("enabled", patch["enabled"], "must_be_boolean")
            values["enabled"] = patch["enabled"]
        return values

    @staticmethod
    def _admin_row(row: ResourceTier, in_use_app_count: int) -> dict[str, Any]:
        return {
            "code": row.code,
            "name": row.name,
            "cpu_millicores": row.cpu_millicores,
            "memory_mb": row.memory_mb,
            "description": row.description,
            "enabled": bool(row.enabled),
            "sort_order": row.sort_order,
            "in_use_app_count": in_use_app_count,
            # The tab hides the retire button on this row and says why — the
            # same fact 16263 enforces server-side.
            "is_default": row.code == DEFAULT_TIER_CODE,
            "update_time": row.update_time.isoformat() if row.update_time else None,
        }

    @staticmethod
    async def _audit_retune(tier_code: str, *, actor, changes: dict[str, dict[str, Any]]) -> None:
        """One ``app.tier_update`` row per successful edit (best effort, like ``release_audit``).

        ``reason`` says what kind of edit it was so the audit page can tell a
        retirement from a retune without opening the row. Tiers are
        platform-level (no ``tenant_id`` column), so the resource side of the
        row is the Root tenant — the operator side is the acting super admin.
        """
        enabled_change = changes.get("enabled")
        if enabled_change is not None:
            reason = "disabled" if enabled_change["to"] is False else "enabled"
        else:
            reason = "retuned"
        try:
            await AuditLogDao.ainsert_v2(
                tenant_id=DEFAULT_TENANT_ID,
                operator_id=actor.user_id,
                operator_name=getattr(actor, "user_name", None),
                operator_tenant_id=int(getattr(actor, "tenant_id", None) or DEFAULT_TENANT_ID),
                action=AppAuditAction.TIER_UPDATE.value,
                target_type=TIER_AUDIT_TARGET_TYPE,
                target_id=tier_code,
                reason=reason,
                metadata={"code": tier_code, "changes": changes},
            )
        except Exception:
            # Best effort by design: an unwritten audit row must not undo a
            # retune that already landed (same shape as release_audit).
            logger.exception(f"app_publish.tier_audit_failed code={tier_code}")


def _rank(code: str) -> int:
    """Stable fallback ordering for codes the seed source did not order."""
    return _SEED_ORDER.index(code) if code in _SEED_ORDER else len(_SEED_ORDER)
