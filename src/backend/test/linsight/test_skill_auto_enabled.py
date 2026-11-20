"""F005: an auto-enabled tenant skill is hidden from pickers and always available.

Reuses the sqlite fixture of ``test_personal_skill_provisioning``: tenant skills
``pdf`` and ``he-tong``, a personal ``pdf`` of USER, all visible to USER.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.linsight.domain.models.linsight_skill import SKILL_SOURCE_BUILTIN, LinsightSkill, LinsightSkillDao
from bisheng.linsight.domain.schemas.skill_schema import SkillBrief
from bisheng.linsight.domain.services import builtin_skill_seeder
from bisheng.linsight.domain.services.skill_service import SkillService
from bisheng.linsight.domain.services.user_skills import UserSkillsService
from test.linsight.test_personal_skill_provisioning import TENANT, USER, env  # noqa: F401


async def test_admin_switch_is_stored_and_listed(env):  # noqa: F811
    assert await LinsightSkillDao.set_auto_enabled("he-tong", True)

    row = await LinsightSkillDao.get_by_name("he-tong")
    assert row.auto_enabled
    assert SkillBrief.from_model(row).auto_enabled is True


async def test_a_personal_skill_cannot_be_auto_enabled(env):  # noqa: F811
    # Only owner 0 rows are touched; the personal ``ting-yong`` of USER is not a tenant skill.
    assert not await LinsightSkillDao.set_auto_enabled("ting-yong", True)


async def test_picker_leaves_out_an_auto_enabled_skill(env, monkeypatch):  # noqa: F811
    await LinsightSkillDao.set_auto_enabled("he-tong", True)

    names = [item.name for item in await SkillService(store=env.store).get_selectable(USER)]

    assert "he-tong" not in names
    assert "pdf" in names


async def test_a_personal_opt_out_does_not_stop_an_auto_enabled_skill(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(
        "bisheng.linsight.domain.services.user_skills.SkillAvailabilityRepository.disabled_ids",
        AsyncMock(return_value={env.contract.id}),
    )
    before = {row.name for row, _ in await UserSkillsService(USER).records()}
    await LinsightSkillDao.set_auto_enabled("he-tong", True)
    after = {row.name for row, _ in await UserSkillsService(USER).records()}

    assert "he-tong" not in before
    assert "he-tong" in after


async def test_a_disabled_skill_stays_off_even_when_auto_enabled(env):  # noqa: F811
    await LinsightSkillDao.set_auto_enabled("he-tong", True)
    await LinsightSkillDao.set_enabled("he-tong", False)

    names = {row.name for row, _ in await UserSkillsService(USER).records()}

    assert "he-tong" not in names


async def test_builtin_reseed_keeps_the_admin_choice(env):  # noqa: F811
    files = {"SKILL.md": b"---\nname: bisheng-pptx\ndescription: v1\n---\n"}
    ref = env.store.write_bundle(TENANT, "bisheng-pptx", files)
    with bypass_tenant_filter():
        await LinsightSkillDao.create(
            LinsightSkill(
                tenant_id=TENANT,
                name="bisheng-pptx",
                display_name="PPT",
                description="v1",
                source=SKILL_SOURCE_BUILTIN,
                object_path=env.store.object_key(TENANT, "bisheng-pptx", ref.content_hash),
                content_hash=ref.content_hash,
            )
        )
    await LinsightSkillDao.set_auto_enabled("bisheng-pptx", True)

    outcome = await builtin_skill_seeder._seed_one(
        env.store,
        TENANT,
        "bisheng-pptx",
        {"description": "v2"},
        {"SKILL.md": b"---\nname: bisheng-pptx\ndescription: v2\n---\n"},
    )

    row = await LinsightSkillDao.get_by_name("bisheng-pptx")
    assert outcome == "updated"
    assert (row.description, row.source, bool(row.auto_enabled)) == ("v2", SKILL_SOURCE_BUILTIN, True)
