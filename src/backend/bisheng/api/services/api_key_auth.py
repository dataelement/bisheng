from fastapi import Request
from typing import Optional
import threading

from bisheng.database.models.api_key import ApiKeyDao
from bisheng.database.models.user import UserDao


class ApiKeyAuth:
    """API Key认证类"""

    @staticmethod
    def get_api_key_from_request(request: Request) -> Optional[str]:
        """从请求中提取API Key"""
        # 优先从Header中获取
        api_key = request.headers.get("X-API-Key") or request.headers.get("Authorization")

        if api_key and api_key.startswith("Bearer "):
            api_key = api_key[7:]  # 移除 "Bearer " 前缀

        # 如果Header中没有，从查询参数中获取
        if not api_key:
            api_key = request.query_params.get("api_key")

        return api_key

    @staticmethod
    def authenticate_api_key(api_key: str) -> Optional[dict]:
        """验证API Key并返回用户信息"""
        if not api_key:
            return None

        # 验证API Key
        api_key_obj = ApiKeyDao.validate_api_key(api_key)
        if not api_key_obj:
            return None

        # 获取用户信息
        user = UserDao.get_user(api_key_obj.user_id)
        if not user or user.delete == 1:  # 用户不存在或被禁用
            return None

        # 异步更新使用统计
        threading.Thread(target=ApiKeyDao.update_usage, args=(api_key_obj.id,)).start()

        # 构造用户信息
        from bisheng.api.services.user_service import gen_user_role

        role, _ = gen_user_role(user)

        return {
            "user_name": user.user_name,
            "user_id": user.user_id,
            "role": role
        }


def get_current_user_by_api_key(request: Request) -> Optional[dict]:
    """通过API Key获取当前用户"""
    api_key = ApiKeyAuth.get_api_key_from_request(request)
    if not api_key:
        return None

    return ApiKeyAuth.authenticate_api_key(api_key)


