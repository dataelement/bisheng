"""User group API router aggregation (F003)."""

from fastapi import APIRouter

from bisheng.user_group.api.endpoints.user_group import router as user_group_crud_router
from bisheng.user_group.api.endpoints.user_group_member import router as user_group_member_router

router = APIRouter(prefix='/user-groups', tags=['UserGroup'])
router.include_router(user_group_crud_router)
router.include_router(user_group_member_router)
