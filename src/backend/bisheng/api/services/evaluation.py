from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from bisheng.api.errcode.assistant import (AssistantInitError, AssistantNameRepeatError,
                                           AssistantNotEditError, AssistantNotExistsError, ToolTypeRepeatError,
                                           ToolTypeEmptyError, ToolTypeNotExistsError, ToolTypeIsPresetError)
from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.services.assistant_base import AssistantUtils
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import (AssistantInfo, AssistantSimpleInfo, AssistantUpdateReq,
                                    StreamData, UnifiedResponseModel, resp_200, resp_500)
from bisheng.cache import InMemoryCache
from bisheng.database.models.assistant import (Assistant, AssistantDao, AssistantLinkDao,
                                               AssistantStatus)
from bisheng.database.models.evaluation import (Evaluation, EvaluationDao)
from bisheng.database.models.flow import Flow, FlowDao
from bisheng.database.models.gpts_tools import GptsToolsDao, GptsToolsRead, GptsToolsTypeRead, GptsTools
from bisheng.database.models.knowledge import KnowledgeDao
from bisheng.database.models.role_access import AccessType, RoleAccessDao
from bisheng.database.models.user import UserDao
from bisheng.database.models.user_role import UserRoleDao
from loguru import logger


class EvaluationService():
    UserCache: InMemoryCache = InMemoryCache()

    @classmethod
    def get_assistant(cls,
                      user: UserPayload,
                      status: int | None = None,
                      page: int = 1,
                      limit: int = 20) -> UnifiedResponseModel[List[Evaluation]]:
        """
        获取测评任务列表
        """
        data = []
        res, total = EvaluationDao.get_all_evaluations(page, limit)

        for one in res:
            simple_dict = one.model_dump(include={
                'id', 'exec_type', 'unique_id', 'status', 'user_id', 'create_time', 'update_time'
            })
            simple_dict['user_name'] = cls.get_user_name(one.user_id)
            data.append(Evaluation(**simple_dict))
        return resp_200(data={'data': data, 'total': total})

    @classmethod
    def get_user_name(cls, user_id: int):
        if not user_id:
            return 'system'
        user = cls.UserCache.get(user_id)
        if user:
            return user.user_name
        user = UserDao.get_user(user_id)
        if not user:
            return f'{user_id}'
        cls.UserCache.set(user_id, user)
        return user.user_name