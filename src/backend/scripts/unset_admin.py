#!/usr/bin/env python3
"""撤销指定用户的平台超级管理员权限, 保留其他角色并补齐普通用户角色.

从 src/backend 执行:
    .venv/bin/python scripts/unset_admin.py 123
    .venv/bin/python scripts/unset_admin.py 123 --apply

默认只读预览; --apply 修改数据库、OpenFGA 和 Redis, 并使旧登录令牌失效.
请在维护窗口执行, 避免同时为该账号授权或手工重放失败队列.
数据库提交后的外部系统失败不会回滚已撤权限, 可用相同命令重试.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# 与权限补偿 Worker 使用同一把锁, 不导入 Worker 以免启动 Celery.
RETRY_LOCK_KEY = "bisheng:lock:retry_failed_tuples"


class UnsetAdminError(RuntimeError):
    """前置条件或撤权核验未通过."""


def emit(phase: str, **data: Any) -> None:
    print(json.dumps({"phase": phase, **data}, ensure_ascii=False), flush=True)


async def load_backend() -> SimpleNamespace:
    # 延迟导入, 确保 --help 不连接服务且 --config 先于配置加载生效.
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_database_connection
    from bisheng.database.constants import AdminRole, DefaultRole
    from bisheng.database.models.failed_tuple import FailedTuple
    from bisheng.database.models.role import Role
    from bisheng.user.domain.models.user import User
    from bisheng.user.domain.models.user_role import UserRole

    db = await get_database_connection()
    return SimpleNamespace(
        db=db,
        session=db.async_session,
        bypass=bypass_tenant_filter,
        User=User,
        UserRole=UserRole,
        Role=Role,
        FailedTuple=FailedTuple,
        admin_role=AdminRole,
        default_role=DefaultRole,
    )


class ExistingFga:
    """只连接已有存储/模型; 核验要求高一致性, HTTP 错误必须向上传递."""

    def __init__(self, http: Any, store_id: str, model_ids: list[str]):
        self.http = http
        self.store_id = store_id
        self.model_ids = model_ids

    @staticmethod
    async def list_all(http: Any, path: str, key: str) -> list[dict]:
        items, token = [], ""
        while True:
            response = await http.get(path, params={"continuation_token": token})
            response.raise_for_status()
            data = response.json()
            items.extend(data[key])
            token = data.get("continuation_token", "")
            if not token:
                return items

    @classmethod
    async def connect(cls, config: Any, http: Any) -> ExistingFga:
        if not config.enabled:
            raise UnsetAdminError("OpenFGA 未启用, 无法核验残留超级管理员关系; 未执行撤权")
        store_id = config.store_id
        if not store_id:
            stores = await cls.list_all(http, "/stores", "stores")
            matches = [item["id"] for item in stores if item.get("name") == config.store_name]
            if len(matches) != 1:
                raise UnsetAdminError("无法唯一定位已有 OpenFGA 存储, 请配置 store_id")
            store_id = matches[0]
        model_id = config.model_id
        if not model_id:
            models = await cls.list_all(http, f"/stores/{store_id}/authorization-models", "authorization_models")
            if not models:
                raise UnsetAdminError("OpenFGA 没有已有授权模型, 未执行撤权")
            model_id = max(item["id"] for item in models)
        model_ids = [model_id]
        if config.dual_model_mode and config.legacy_model_id:
            model_ids.append(config.legacy_model_id)
        return cls(http, store_id, list(dict.fromkeys(model_ids)))

    @staticmethod
    def key(user_id: int) -> dict[str, str]:
        return {"user": f"user:{user_id}", "relation": "super_admin", "object": "system:global"}

    async def is_super(self, user_id: int) -> bool:
        results = []
        for model_id in self.model_ids:
            response = await self.http.post(
                f"/stores/{self.store_id}/check",
                json={
                    "tuple_key": self.key(user_id),
                    "authorization_model_id": model_id,
                    "consistency": "HIGHER_CONSISTENCY",
                },
            )
            response.raise_for_status()
            allowed = response.json().get("allowed")
            if not isinstance(allowed, bool):
                raise UnsetAdminError("OpenFGA 返回的权限结果无效")
            results.append(allowed)
        return any(results)

    async def revoke(self, user_id: int) -> None:
        if await self.is_super(user_id):
            # 关系存储为同一个 store, 不随授权模型复制; 删除一次即可.
            response = await self.http.post(
                f"/stores/{self.store_id}/write",
                json={"deletes": {"tuple_keys": [self.key(user_id)]}, "authorization_model_id": self.model_ids[0]},
            )
            response.raise_for_status()
        if await self.is_super(user_id):
            raise UnsetAdminError("OpenFGA 撤权后仍返回超级管理员, 请重试并排查并发授权")


async def read_state(backend: Any, session: Any, user_id: int) -> dict:
    from sqlmodel import select

    b = backend
    user = (await session.exec(select(b.User).where(b.User.user_id == user_id))).first()
    if user is None:
        raise UnsetAdminError(f"用户 user_id={user_id} 不存在")
    roles = (await session.exec(select(b.UserRole).where(b.UserRole.user_id == user_id))).all()
    ordinary = (await session.exec(select(b.Role).where(b.Role.id == b.default_role))).first()
    if ordinary is None:
        raise UnsetAdminError("默认普通用户角色不存在, 未执行撤权")
    pending = (
        await session.exec(
            select(b.FailedTuple).where(
                b.FailedTuple.fga_user == f"user:{user_id}",
                b.FailedTuple.relation == "super_admin",
                b.FailedTuple.object == "system:global",
                b.FailedTuple.status == "pending",
            )
        )
    ).all()
    other_admins = (
        await session.exec(
            select(b.User.user_id)
            .join(b.UserRole, b.UserRole.user_id == b.User.user_id)
            .where(b.UserRole.role_id == b.admin_role, b.User.user_id != user_id, b.User.delete == 0)
        )
    ).all()
    return {
        "user_id": user_id,
        "user_name": user.user_name,
        "disabled": bool(user.delete),
        "roles": [{"role_id": row.role_id, "tenant_id": row.tenant_id} for row in roles],
        "default_role_tenant_id": ordinary.tenant_id,
        "pending_writes": [row.id for row in pending if row.action == "write"],
        "pending_deletes": [row.id for row in pending if row.action == "delete"],
        "other_active_admin_ids": sorted(set(other_admins)),
    }


async def snapshot(backend: Any, user_id: int) -> dict:
    with backend.bypass():
        async with backend.session() as session:
            return await read_state(backend, session, user_id)


async def prepare_database(backend: Any, user_id: int, was_fga_super: bool) -> dict:
    from sqlalchemy import delete, update
    from sqlmodel import select

    b = backend
    with b.bypass():
        async with b.session() as session:
            # 固定顺序锁定管理员角色行, 防止本脚本并发撤销最后的管理员.
            await session.exec(
                select(b.UserRole)
                .where(b.UserRole.role_id == b.admin_role)
                .order_by(b.UserRole.user_id)
                .with_for_update()
            )
            await session.exec(select(b.User).where(b.User.user_id == user_id).with_for_update())
            state = await read_state(b, session, user_id)
            role_ids = {row["role_id"] for row in state["roles"]}
            if (b.admin_role in role_ids or was_fga_super) and not state["other_active_admin_ids"]:
                raise UnsetAdminError("拒绝撤销: 没有其他未禁用的数据库超级管理员")
            if b.default_role not in role_ids:
                session.add(
                    b.UserRole(user_id=user_id, role_id=b.default_role, tenant_id=state["default_role_tenant_id"])
                )
            await session.exec(
                delete(b.UserRole).where(b.UserRole.user_id == user_id, b.UserRole.role_id == b.admin_role)
            )
            if state["pending_writes"]:
                await session.exec(
                    update(b.FailedTuple)
                    .where(b.FailedTuple.id.in_(state["pending_writes"]))
                    .values(status="dead", error_message="Cancelled by unset_admin.py; superseded by revocation")
                )
            changed = (
                b.admin_role in role_ids
                or b.default_role not in role_ids
                or was_fga_super
                or bool(state["pending_writes"])
            )
            if changed and not state["pending_deletes"]:
                # 与角色删除同一事务保存补偿, 外部系统失败时可重试撤权.
                session.add(
                    b.FailedTuple(
                        action="delete",
                        fga_user=f"user:{user_id}",
                        relation="super_admin",
                        object="system:global",
                        tenant_id=state["default_role_tenant_id"],
                        error_message="unset_admin.py revocation pending verification",
                    )
                )
            if changed:
                await session.exec(
                    update(b.User).where(b.User.user_id == user_id).values(token_version=b.User.token_version + 1)
                )
            await session.commit()
            return state


async def finish_database(backend: Any, user_id: int) -> None:
    from sqlalchemy import update

    b = backend
    with b.bypass():
        async with b.session() as session:
            await session.exec(
                update(b.FailedTuple)
                .where(
                    b.FailedTuple.fga_user == f"user:{user_id}",
                    b.FailedTuple.relation == "super_admin",
                    b.FailedTuple.object == "system:global",
                    b.FailedTuple.action == "delete",
                    b.FailedTuple.status == "pending",
                )
                .values(status="succeeded", error_message="Verified by unset_admin.py")
            )
            await session.commit()


async def invalidate_caches(redis: Any, user_id: int) -> None:
    # 直接操作连接, 避免缓存封装吞掉故障; 覆盖所有租户的该用户缓存.
    for prefix in ("perm:chk", "perm:lst"):
        async for key in redis.scan_iter(match=f"{prefix}:*:{user_id}:*", count=100):
            await redis.delete(key)
    for key in (f"user:{user_id}:is_super", f"user:{user_id}:token_version"):
        await redis.delete(key)


@asynccontextmanager
async def retry_guard(redis: Any):
    lock = redis.lock(RETRY_LOCK_KEY, timeout=60, blocking=False)
    if not await lock.acquire():
        raise UnsetAdminError("权限补偿任务或其他撤权脚本正在执行, 请稍后重试")

    async def renew() -> None:
        while True:
            await asyncio.sleep(10)
            if not await lock.reacquire():
                raise UnsetAdminError("权限补偿锁续期失败")

    task = asyncio.create_task(renew())

    async def check() -> None:
        if task.done():
            await task
        if not await lock.owned():
            raise UnsetAdminError("权限补偿锁已丢失, 撤权未完成")

    try:
        yield check
        await check()
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            if await lock.owned():
                await lock.release()


async def execute(backend: Any, fga: Any, user_id: int, *, apply: bool, redis: Any = None) -> dict:
    state = await snapshot(backend, user_id)
    state["fga_super_admin"] = await fga.is_super(user_id)
    emit(
        "preview",
        **state,
        apply=apply,
        remove_role_id=backend.admin_role,
        add_default_role=not any(row["role_id"] == backend.default_role for row in state["roles"]),
    )
    if not apply:
        return state
    if redis is None:
        raise UnsetAdminError("Redis 不可用, 未执行撤权")
    async with retry_guard(redis) as check_lock:
        await check_lock()
        before = await prepare_database(backend, user_id, await fga.is_super(user_id))
        emit("database_committed", user_id=user_id, message="角色撤权及补偿已提交; 后续失败请重试, 不会自动恢复超管")
        try:
            await check_lock()
            await fga.revoke(user_id)
        finally:
            # 即使 OpenFGA 失败, 也刷新已经提交的数据库权限和令牌状态.
            await invalidate_caches(redis, user_id)
        await check_lock()
        after = await snapshot(backend, user_id)
        expected = {(r["role_id"], r["tenant_id"]) for r in before["roles"] if r["role_id"] != backend.admin_role}
        if not any(role == backend.default_role for role, _ in expected):
            expected.add((backend.default_role, before["default_role_tenant_id"]))
        actual = {(r["role_id"], r["tenant_id"]) for r in after["roles"]}
        if actual != expected or after["pending_writes"] or await fga.is_super(user_id):
            raise UnsetAdminError("撤权核验未通过, 请停止并发授权后重试")
        await finish_database(backend, user_id)
        await check_lock()
    emit("verified", user_id=user_id, roles=after["roles"], message="平台超级管理员已撤销; 其他角色保留, 请重新登录")
    return after


async def run(args: argparse.Namespace) -> int:
    import httpx

    from bisheng.common.services.config_service import settings

    backend = None
    redis_client = None
    try:
        backend = await load_backend()
        config = settings.openfga
        async with httpx.AsyncClient(base_url=config.api_url, timeout=config.timeout, trust_env=False) as http:
            fga = await ExistingFga.connect(config, http)
            redis = None
            if args.apply:
                from bisheng.core.cache.redis_manager import get_redis_client

                redis_client = await get_redis_client()
                redis = redis_client.async_connection
                await redis.ping()
            await execute(backend, fga, args.user_id, apply=args.apply, redis=redis)
        return 0
    finally:
        try:
            if redis_client is not None:
                await redis_client.aclose()
        finally:
            if backend is not None:
                await backend.db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user_id", type=int, help="目标用户 ID, 不是用户名")
    parser.add_argument("--apply", action="store_true", help="执行撤权; 默认只读预览")
    parser.add_argument("--config", help="BiSheng 配置文件, 与 execute_sql.py 一致")
    args = parser.parse_args()
    if args.user_id <= 0:
        parser.error("user_id 必须为正整数")
    if args.config:
        os.environ["config"] = args.config
    try:
        return asyncio.run(run(args))
    except Exception as exc:
        # 不输出连接串或底层 SQL 参数; 已提交阶段由上方审计行明确标识.
        message = str(exc) if isinstance(exc, UnsetAdminError) else "服务或数据库操作失败, 请检查服务日志后重试"
        emit("failed", error_type=type(exc).__name__, message=message)
        return 1


if __name__ == "__main__":
    sys.exit(main())
