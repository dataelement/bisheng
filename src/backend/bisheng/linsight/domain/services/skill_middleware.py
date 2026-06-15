"""Skill loading + per-run whitelist middleware for the deepagents kernel.

F035 Track D (design §7.2, deviation D8): deepagents 0.6.x has no native
whitelist hook — ``SkillsMiddleware`` only loads sources. We subclass it and
filter the loaded ``skills_metadata`` in ``(a)before_agent``:

- **built-in skills** (``SKILLS_ROOT/built-in/``) always pass — they are kernel
  capabilities, never exposed to the UI and never constrained by the whitelist;
- **tenant custom skills** (``SKILLS_ROOT/data/skills/{tenant_id}/``) must be
  enabled at governance level (``linsight_skill.enabled``, resolved at assembly
  time) AND present in the per-run whitelist
  ``config.configurable.active_skills`` (C3 contract: list of skill names;
  ``[]`` disables all custom skills; a missing key counts as "no constraint"
  for non-UI callers only — the product UI always sends an explicit list).

The single-subclass shape replaces the design-§7.2 two-middleware split, which
removes the ordering hazard against other middlewares (recorded as deviation D8).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.skills import SkillsMiddleware, SkillsState, SkillsStateUpdate
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from bisheng.linsight.domain.models.linsight_skill import LinsightSkillDao
from bisheng.linsight.domain.services.skill_store import BUILTIN_DIR, SkillStore

if TYPE_CHECKING:
    from deepagents.middleware.skills import SkillMetadata

ACTIVE_SKILLS_CONFIG_KEY = "active_skills"

_BUILTIN_SOURCE = f"/{BUILTIN_DIR}/"


class TenantSkillsMiddleware(SkillsMiddleware):
    """SkillsMiddleware + tenant governance (enabled) + per-run whitelist filter."""

    def __init__(self, tenant_id: int, enabled_names: set[str], store: SkillStore | None = None):
        store = store or SkillStore()
        store.builtin_dir().mkdir(parents=True, exist_ok=True)
        store.tenant_dir(tenant_id).mkdir(parents=True, exist_ok=True)
        # virtual_mode anchors all paths inside SKILLS_ROOT and blocks traversal (design §7.1).
        backend = FilesystemBackend(root_dir=str(store.root), virtual_mode=True)
        super().__init__(
            backend=backend,
            sources=[
                (_BUILTIN_SOURCE, "Built-in"),
                (f"/data/skills/{tenant_id}/", "Tenant"),
            ],
        )
        self._tenant_id = tenant_id
        self._enabled_names = set(enabled_names)

    # -- whitelist filtering -------------------------------------------------
    def _filter_update(self, update: SkillsStateUpdate | None, config: RunnableConfig) -> SkillsStateUpdate | None:
        if not update or "skills_metadata" not in update:
            return update
        active = (config or {}).get("configurable", {}).get(ACTIVE_SKILLS_CONFIG_KEY)
        active_set = set(active) if active is not None else None
        update["skills_metadata"] = [
            skill for skill in update["skills_metadata"] if self._skill_allowed(skill, active_set)
        ]
        return update

    def _skill_allowed(self, skill: SkillMetadata, active_set: set[str] | None) -> bool:
        if skill["path"].startswith(_BUILTIN_SOURCE):
            return True
        if skill["name"] not in self._enabled_names:
            return False
        # None = no per-run constraint (robustness fallback; UI always sends a list).
        return active_set is None or skill["name"] in active_set

    def before_agent(self, state: SkillsState, runtime: Runtime, config: RunnableConfig) -> SkillsStateUpdate | None:  # ty: ignore[invalid-method-override]
        return self._filter_update(super().before_agent(state, runtime, config), config)

    async def abefore_agent(
        self, state: SkillsState, runtime: Runtime, config: RunnableConfig
    ) -> SkillsStateUpdate | None:  # ty: ignore[invalid-method-override]
        return self._filter_update(await super().abefore_agent(state, runtime, config), config)


async def make_skills_middleware(tenant_id: int, store: SkillStore | None = None) -> TenantSkillsMiddleware:
    """Assembly-time factory for Track A (`_create_agent` middleware list).

    Resolves the governance-enabled skill set from DB; the caller must already
    hold the tenant context (worker re-establishes it before task execution,
    design §6.5).
    """
    enabled = {skill.name for skill in await LinsightSkillDao.list_enabled()}
    return TenantSkillsMiddleware(tenant_id=tenant_id, enabled_names=enabled, store=store)
