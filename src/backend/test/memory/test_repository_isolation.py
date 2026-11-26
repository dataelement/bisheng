"""Data-access isolation of memory (AC-01, AC-02, AC-05, AC-06, AC-07; design decision 9)."""

import asyncio
import uuid
from datetime import datetime

import pytest
from sqlmodel import select

from bisheng.memory.domain.models.memory_item import STATUS_ACTIVE, STATUS_DELETED, MemoryItem
from bisheng.memory.domain.models.memory_user_setting import MemoryUserSetting
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.repositories.item_repository import ItemRepository
from bisheng.memory.domain.repositories.setting_repository import SettingRepository
from bisheng.memory.domain.services.context import build_user_context
from test.memory.conftest import TENANT_A, TENANT_B, USER_1, USER_2


def _item(ctx, content, **kw):
    return MemoryItem(
        id=str(uuid.uuid4()),
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        type=kw.pop("type", "fact"),
        content=content,
        status=kw.pop("status", STATUS_ACTIVE),
        recorded_at=datetime(2026, 11, 13, 10),
        origin="explicit",
        source_scene="daily",
        **kw,
    )


async def _seed(ctx, *contents):
    async with _db.async_session() as s:
        for c in contents:
            await ItemRepository.insert(s, ctx, _item(ctx, c))
        await s.commit()


async def _list(ctx):
    async with _db.async_session() as s:
        return [i.content for i in await ItemRepository.list_active(s, ctx)]


async def test_ac01_ac02_user_cannot_read_other_user(memory_db, make_ctx):
    """AC-01/AC-02: user 1 never reads user 2's items in the same tenant."""
    await _seed(make_ctx(user_id=USER_1), "甲的偏好")
    await _seed(make_ctx(user_id=USER_2), "乙的偏好")
    assert await _list(make_ctx(user_id=USER_1)) == ["甲的偏好"]
    assert await _list(make_ctx(user_id=USER_2)) == ["乙的偏好"]


async def test_ac05_tenant_isolation(memory_db, make_ctx):
    """AC-05: an item in tenant A is not readable in tenant B for the same user id."""
    await _seed(make_ctx(tenant_id=TENANT_A), "A 租户里的记忆")
    assert await _list(make_ctx(tenant_id=TENANT_B)) == []


async def test_ac05_visible_multi_tenant_identity_reads_current_only(memory_db, make_ctx, identities, tenant_ctx):
    """A user who can see tenants A and B reads only the current tenant's items."""
    await _seed(make_ctx(tenant_id=TENANT_A), "A 的")
    await _seed(make_ctx(tenant_id=TENANT_B), "B 的")
    tenant_ctx(TENANT_B)
    ctx = build_user_context(identities.multi)
    assert ctx.tenant_id == TENANT_B
    assert await _list(ctx) == ["B 的"]


async def test_global_super_admin_reads_only_own_items_in_current_tenant(memory_db, make_ctx, identities, tenant_ctx):
    await _seed(make_ctx(tenant_id=TENANT_A, user_id=1), "超管自己的")
    await _seed(make_ctx(tenant_id=TENANT_B, user_id=1), "超管在 B 的")
    await _seed(make_ctx(tenant_id=TENANT_A, user_id=USER_1), "别人的")
    tenant_ctx(TENANT_A)
    ctx = build_user_context(identities.superadmin)
    assert await _list(ctx) == ["超管自己的"]


async def test_batch_update_and_delete_scoped(memory_db, make_ctx):
    me = make_ctx()
    other_user = make_ctx(user_id=USER_2)
    other_tenant = make_ctx(tenant_id=TENANT_B)
    for c in (me, other_user, other_tenant):
        await _seed(c, "同样的内容")
    async with _db.async_session() as s:
        ids = [i.id for i in (await s.exec(select(MemoryItem))).all()]
        # Even when ids of other users are passed, only my rows change.
        changed = await ItemRepository.update_fields(s, me, ids, status=STATUS_DELETED)
        await s.commit()
    assert changed == 1
    assert await _list(me) == []
    assert await _list(other_user) == ["同样的内容"]
    assert await _list(other_tenant) == ["同样的内容"]
    async with _db.async_session() as s:
        removed = await ItemRepository.delete_all(s, me)
        await s.commit()
        remaining = (await s.exec(select(MemoryItem))).all()
    assert removed == 1
    assert len(remaining) == 2


async def test_ac06_ac07_tenant_change_and_return(memory_db, identities, tenant_ctx, make_ctx):
    """AC-06/AC-07: items stay in tenant A, unreadable from B, readable again back in A."""
    await _seed(make_ctx(tenant_id=TENANT_A), "原租户的记忆")
    tenant_ctx(TENANT_B)
    assert await _list(build_user_context(identities.user1)) == []
    tenant_ctx(TENANT_A)
    assert await _list(build_user_context(identities.user1)) == ["原租户的记忆"]
    async with _db.async_session() as s:
        rows = (await s.exec(select(MemoryItem))).all()
    assert [r.tenant_id for r in rows] == [TENANT_A]  # not migrated


async def test_setting_concurrent_creation(memory_db, make_ctx):
    ctx = make_ctx()
    results = await asyncio.gather(*[SettingRepository.ensure(ctx) for _ in range(5)])
    assert all(r.tenant_id == TENANT_A and r.user_id == USER_1 for r in results)
    async with _db.async_session() as s:
        rows = (await s.exec(select(MemoryUserSetting))).all()
    assert len(rows) == 1
    assert rows[0].enabled is True


async def test_rev_bump_shares_transaction_with_item_change(memory_db, make_ctx):
    ctx = make_ctx()
    async with _db.async_session() as s:
        await ItemRepository.insert(s, ctx, _item(ctx, "要回滚的"))
        await SettingRepository.bump_rev(s, ctx)
        await s.rollback()
    setting = await SettingRepository.get(ctx)
    assert (setting.rev if setting else 0) == 0
    assert await _list(ctx) == []
    async with _db.async_session() as s:
        await ItemRepository.insert(s, ctx, _item(ctx, "提交的"))
        await SettingRepository.bump_rev(s, ctx)
        await s.commit()
    assert (await SettingRepository.get(ctx)).rev == 1
    assert await _list(ctx) == ["提交的"]


def test_repository_methods_require_context():
    """Decision 9: every item/setting repository method takes a MemoryContext."""
    import inspect

    for repo in (ItemRepository, SettingRepository):
        for name, fn in inspect.getmembers(repo, predicate=inspect.ismethod):
            if name.startswith("_"):
                continue
            assert "ctx" in inspect.signature(fn).parameters, f"{repo.__name__}.{name} lacks ctx"


@pytest.mark.parametrize("missing", ["tenant_id", "user_id"])
def test_scope_filter_requires_tenant_and_user(make_ctx, missing):
    from bisheng.memory.domain.ports import build_scope_filter

    ctx = make_ctx()
    setattr(ctx, missing, None)
    with pytest.raises(ValueError):
        build_scope_filter(ctx)
