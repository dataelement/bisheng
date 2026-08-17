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

from bisheng.app_runtime.domain.constants import DEFAULT_TIERS
from bisheng.common.errcode.app_publish import AppTierUnavailableError
from bisheng.common.services.config_service import settings
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app_version import TERMINAL_STATE_ONLINE, AppVersion
from bisheng.database.models.resource_tier import DEFAULT_TIER_CODE, ResourceTier, ResourceTierDao

#: Order tiers are displayed in when the seed source does not say otherwise.
_SEED_ORDER = ("light", "standard", "performance")


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
    async def update_tier(cls, tier_code: str, **patch: Any) -> bool:
        """Retune one tier (super-admin surface, deferred wave). ``code`` itself is not editable."""
        async with get_async_db_session() as session:
            changed = await ResourceTierDao.aupdate_row(session, tier_code, **patch)
            await session.commit()
        return changed

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


def _rank(code: str) -> int:
    """Stable fallback ordering for codes the seed source did not order."""
    return _SEED_ORDER.index(code) if code in _SEED_ORDER else len(_SEED_ORDER)
