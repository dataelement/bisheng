"""User group API router aggregation (F003)."""

from fastapi import APIRouter

from bisheng.user_group.api.endpoints.user_group import router as user_group_crud_router
from bisheng.user_group.api.endpoints.user_group_member import router as user_group_member_router

router = APIRouter(prefix='/user-groups', tags=['UserGroup'])
# 成员子路径先于 CRUD 的 `/{group_id}` 注册，避免极端路由匹配顺序问题
router.include_router(user_group_member_router)
router.include_router(user_group_crud_router)
