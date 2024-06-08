import os
import uuid
import io
from typing import List

from fastapi import UploadFile, HTTPException
import pandas as pd

from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import (UnifiedResponseModel, resp_200)
from bisheng.cache import InMemoryCache
from bisheng.database.models.flow import FlowDao
from bisheng.database.models.flow_version import FlowVersionDao
from bisheng.database.models.assistant import AssistantDao
from bisheng.api.services.flow import FlowService
from bisheng.database.models.evaluation import (Evaluation, EvaluationDao, ExecType, EvaluationTaskStatus)
from bisheng.database.models.user import UserDao
from bisheng.utils.minio_client import MinioClient
from fastapi.encoders import jsonable_encoder
from bisheng.utils.logger import logger
from bisheng.api.services.assistant_agent import AssistantAgent


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
    def delete_evaluation(cls, evaluation_id: int, user_payload: UserPayload) -> UnifiedResponseModel:
        evaluation = EvaluationDao.get_user_one_evaluation(user_payload.user_id, evaluation_id)
        if not evaluation:
            raise HTTPException(status_code=404, detail='Evaluation not found')

        EvaluationDao.delete_evaluation(evaluation)
        return resp_200()

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

    @classmethod
    def read_csv_file(cls, file_path: str):
        minio_client = MinioClient()
        resp = minio_client.download_minio(file_path)
        if resp is None:
            return None
        new_data = io.BytesIO()
        for d in resp.stream(32 * 1024):
            new_data.write(d)
        resp.close()
        resp.release_conn()
        new_data.seek(0)
        return new_data

    @classmethod
    def parse_csv(cls, file_data: io.BytesIO):
        df = pd.read_csv(file_data)
        df = df.dropna(axis=0, how='all').dropna(axis=1, how='all')
        if df.shape[1] < 2:
            raise ValueError("CSV file must have at least two columns")
        if df.columns[0] != 'question' or df.columns[1] != 'ground_truth':
            raise ValueError(
                "CSV file must have 'question' as the first column and 'ground_truth' as the second column")
        formatted_data = [{"question": row[0], "ground_truth": row[1]} for row in df.values]
        return formatted_data


async def add_evaluation_task(evaluation_id: int):
    evaluation = EvaluationDao.get_one_evaluation(evaluation_id=evaluation_id)
    if not evaluation:
        return
    try:
        file_data = EvaluationService.read_csv_file(evaluation.file_path)
        csv_data = EvaluationService.parse_csv(file_data)

        if evaluation.exec_type == ExecType.FLOW.value:
            flow_version = FlowVersionDao.get_version_by_id(version_id=evaluation.version)
            if not flow_version:
                raise Exception("Flow version not found")
            for csv_item in csv_data:
                flow_index, flow_result = await FlowService.exec_flow_node(inputs={"input": csv_item.get('question')},
                                                                           tweaks={},
                                                                           index=0,
                                                                           versions=[flow_version])
                csv_item["answer"] = flow_result.get(flow_version.id)

        if evaluation.exec_type == ExecType.ASSISTANT.value:
            assistant = AssistantDao.get_one_assistant(evaluation.unique_id)
            if not assistant:
                raise Exception("Assistant not found")
            gpts_agent = AssistantAgent(assistant_info=assistant, chat_id="")
            await gpts_agent.init_assistant()
            for csv_item in csv_data:
                messages = await gpts_agent.run(csv_item.get('question'))
                if len(messages):
                    csv_item["answer"] = messages[0].content

        print(csv_data)
    except Exception as e:
        logger.error(f'Evaluation task failed id={evaluation_id} {e}')
        evaluation.status = EvaluationTaskStatus.failed.value
        EvaluationDao.update_evaluation(evaluation=evaluation)
