import os
import uuid
from typing import List

from fastapi import UploadFile

from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import (UnifiedResponseModel, resp_200)
from bisheng.cache import InMemoryCache
from bisheng.database.models.flow import FlowDao
from bisheng.database.models.flow_version import FlowVersionDao
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.evaluation import (Evaluation, EvaluationDao, ExecType)
from bisheng.database.models.user import UserDao
from bisheng.utils.minio_client import MinioClient
from fastapi.encoders import jsonable_encoder


class EvaluationService:
    UserCache: InMemoryCache = InMemoryCache()

    @classmethod
    def get_evaluation(cls,
                       user: UserPayload,
                       page: int = 1,
                       limit: int = 20) -> UnifiedResponseModel[List[Evaluation]]:
        """
        获取测评任务列表
        """
        data = []
        res_evaluations, total = EvaluationDao.get_my_evaluations(user.user_id, page, limit)

        # 技能ID列表
        flow_ids = []
        # 助手ID列表
        assistant_ids = []
        # 版本ID列表
        flow_version_ids = []

        for one in res_evaluations:
            if one.exec_type == ExecType.FLOW.value:
                flow_ids.append(one.unique_id)
                if one.version:
                    flow_version_ids.append(one.version)
            if one.exec_type == ExecType.ASSISTANT.value:
                assistant_ids.append(one.unique_id)

        flow_names = {}
        flow_versions = {}
        assistant_names = {}

        if flow_ids:
            flows = FlowDao.get_flow_by_ids(flow_ids=flow_ids)
            flow_names = {str(one.id): one.name for one in flows}

        if flow_version_ids:
            versions = FlowVersionDao.get_list_by_ids(ids=flow_version_ids)
            flow_versions = {one.id: one.name for one in versions}

        if assistant_ids:
            assistants = AssistantDao.get_assistants_by_ids(assistant_ids=assistant_ids)
            assistant_names = {str(one.id): one.name for one in assistants}

        for one in res_evaluations:
            evaluation_item = jsonable_encoder(one)
            if one.exec_type == ExecType.FLOW.value:
                evaluation_item['unique_name'] = flow_names.get(one.unique_id)
            if one.exec_type == ExecType.ASSISTANT.value:
                evaluation_item['unique_name'] = assistant_names.get(one.unique_id)
            if one.version:
                evaluation_item['version_name'] = flow_versions.get(one.version)

            evaluation_item['user_name'] = cls.get_user_name(one.user_id)
            data.append(evaluation_item)

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

    @classmethod
    def upload_file(cls, file: UploadFile):
        minio_client = MinioClient()
        file_id = uuid.uuid4().hex
        file_name = file.filename

        file_ext = os.path.basename(file.filename).split('.')[-1]
        file_path = f'{EvaluationService.get_file_root()}/{file_id}.{file_ext}'
        minio_client.upload_minio_file(file_path, file.file, file.size, content_type=file.content_type)
        return file_name, file_path

    @classmethod
    def get_file_root(cls):
        return "evaluation/dataset"
