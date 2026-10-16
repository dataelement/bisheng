from abc import ABC, abstractmethod

from bisheng.linsight.domain.models.linsight_skill import LinsightSkill


class SkillRepository(ABC):
    """Read-only skill lookups used by callers outside task mode (F078)."""

    @abstractmethod
    async def list_by_names(self, names: list[str]) -> list[LinsightSkill]:
        """Return the current tenant's skills with these names, enabled or not.

        Disabled rows are included so the caller can tell a disabled skill from
        a deleted one. Names with no row are simply absent from the result.
        """
