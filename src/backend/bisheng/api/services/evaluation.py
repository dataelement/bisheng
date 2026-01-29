import asyncio
import io
import json
import os
from collections import defaultdict
from copy import deepcopy
from io import BytesIO
from typing import List

import numpy as np
import pandas as pd
from bisheng_ragas import evaluate
from bisheng_ragas.llms.langchain import LangchainLLM
from bisheng_ragas.metrics import AnswerCorrectnessBisheng
from datasets import Dataset
from fastapi import UploadFile, HTTPException
from fastapi.encoders import jsonable_encoder
from loguru import logger

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.services.flow import FlowService
from bisheng.api.utils import build_flow, build_input_keys_response
from bisheng.api.v1.schema.workflow import WorkflowEventType
from bisheng.api.v1.schemas import (UnifiedResponseModel, resp_200)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.cache import InMemoryCache
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.evaluation import (Evaluation, EvaluationDao, ExecType, EvaluationTaskStatus)
from bisheng.database.models.flow import FlowDao
from bisheng.database.models.flow_version import FlowVersionDao, FlowVersion
from bisheng.graph.graph.base import Graph
from bisheng.llm.domain.services import LLMService
from bisheng.user.domain.models.user import UserDao
from bisheng.utils import generate_uuid
from bisheng.worker.workflow.redis_callback import RedisCallback
from bisheng.worker.workflow.tasks import execute_workflow, continue_workflow, workflow_stateful_worker
from bisheng.workflow.common.workflow import WorkflowStatus

expire = 600


class EvaluationService:
    UserCache: InMemoryCache = InMemoryCache()

    @classmethod
    def get_evaluation(cls,
                       user: UserPayload,
                       page: int = 1,
                       limit: int = 20) -> UnifiedResponseModel[List[Evaluation]]:
        """
        Get a list of assessment tasks
        """
        data = []
        res_evaluations, total = EvaluationDao.get_my_evaluations(user.user_id, page, limit)

        # SkillIDVertical
        flow_ids = []
        # assistantIDVertical
        assistant_ids = []
        # VersionIDVertical
        flow_version_ids = []

        for one in res_evaluations:
            if one.exec_type in [ExecType.FLOW.value, ExecType.WORKFLOW.value]:
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

        redis_client = get_redis_client_sync()

        for one in res_evaluations:
            evaluation_item = jsonable_encoder(one)
            if one.exec_type in [ExecType.FLOW.value, ExecType.WORKFLOW.value]:
                evaluation_item['unique_name'] = flow_names.get(one.unique_id)
            if one.exec_type == ExecType.ASSISTANT.value:
                evaluation_item['unique_name'] = assistant_names.get(one.unique_id)
            if one.version:
                evaluation_item['version_name'] = flow_versions.get(one.version)
            if one.result_score:
                evaluation_item['result_score'] = json.loads(one.result_score) if isinstance(one.result_score,
                                                                                             str) else one.result_score

            # Processing Task Progress
            if one.status != EvaluationTaskStatus.running.value:
                evaluation_item['progress'] = f'100%'
            elif redis_client.exists(EvaluationService.get_redis_key(one.id)):
                evaluation_item['progress'] = f'{redis_client.get(EvaluationService.get_redis_key(one.id))}%'
            else:
                evaluation_item['progress'] = f'0%'

            # Make sure the error description is returned to the front-end
            evaluation_item['description'] = one.description or ''
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
        minio_client = get_minio_storage_sync()
        file_id = generate_uuid()
        file_name = file.filename

        file_ext = os.path.basename(file.filename).split('.')[-1]
        file_path = f'evaluation/dataset/{file_id}.{file_ext}'
        minio_client.put_object_sync(bucket_name=minio_client.bucket, object_name=file_path, file=file.file.read(),
                                     content_type=file.content_type)
        return file_name, file_path

    @classmethod
    def upload_result_file(cls, df: pd.DataFrame):
        minio_client = get_minio_storage_sync()
        file_id = generate_uuid()

        csv_buffer = io.BytesIO()
        df.to_csv(csv_buffer, index=False)
        csv_buffer.seek(0)

        file_path = f'evaluation/result/{file_id}.csv'
        minio_client.put_object_sync(
            bucket_name=minio_client.bucket,
            object_name=file_path,
            file=csv_buffer.read(),
            content_type='application/csv')
        return file_path

    @classmethod
    def read_csv_file(cls, file_path: str):
        minio_client = get_minio_storage_sync()
        resp = minio_client.get_object_sync(bucket_name=minio_client.bucket, object_name=file_path)
        if resp is None:
            return None
        return BytesIO(resp)

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

    @classmethod
    def get_redis_key(cls, evaluation_id: int):
        return f'evaluation_task_progress_{evaluation_id}'

    @classmethod
    async def get_input_keys(cls, flow_id: str, version_id: int):
        artifacts = {}
        try:
            version_info = FlowVersionDao.get_version_by_id(version_id)
            if not version_info:
                return {"input": ""}

            # L1 Users, usingbuildProcess
            try:
                async for message in build_flow(graph_data=version_info.data,
                                                artifacts=artifacts,
                                                process_file=False,
                                                flow_id=flow_id,
                                                chat_id=None):
                    if isinstance(message, Graph):
                        graph = message

            except Exception as e:
                logger.error(f'evaluation task get_input_keys {e}')
                return {"input": ""}

            await graph.abuild()
            # Now we  need to check the input_keys to send them to the client
            input_keys_response = {
                'input_keys': []
            }
            input_nodes = graph.get_input_nodes()
            for node in input_nodes:
                if hasattr(await node.get_result(), 'input_keys'):
                    input_keys = build_input_keys_response(await node.get_result(), artifacts)
                    input_keys['input_keys'].update({'id': node.id})
                    input_keys_response['input_keys'].append(input_keys.get('input_keys'))
                elif 'fileNode' in node.output:
                    input_keys_response['input_keys'].append({
                        'file_path': '',
                        'type': 'file',
                        'id': node.id
                    })
            if len(input_keys_response.get("input_keys")):
                input_item = input_keys_response.get("input_keys")[0]
                del input_item["id"]
                return input_item
        finally:
            pass
        return {"input": ""}


def execute_workflow_get_answer(workflow_info: FlowVersion, evaluation: Evaluation, question: str) -> str:
    # Initialize workflow
    unique_id = generate_uuid()
    workflow_id = evaluation.unique_id
    chat_id = ""
    user_id = evaluation.user_id
    workflow = RedisCallback(unique_id, workflow_id, chat_id, user_id)
    workflow.set_workflow_data(workflow_info.data)
    workflow.set_workflow_status(WorkflowStatus.WAITING.value)
    hash_key = generate_uuid()
    worker_node = workflow_stateful_worker.find_task_node_sync(hash_key)

    execute_workflow.apply_async([unique_id, workflow_id, chat_id, user_id], queue=worker_node)

    # Listen for execution results of workflows
    input_event = None
    for event in workflow.sync_get_response_until_break():
        input_event = event

    status_info = workflow.get_workflow_status()
    if status_info["status"] == WorkflowStatus.FAILED.value:
        raise Exception(status_info.get("reason", "workflow run failed"))
    elif status_info['status'] == WorkflowStatus.SUCCESS.value:
        raise Exception("Only Q&A type workflows are currently supported")
    elif status_info['status'] == WorkflowStatus.INPUT.value:
        if not input_event or input_event.message.get('input_schema', {}).get("tab") == "form_input":
            raise Exception("Only Q&A type workflows are currently supported")
        # Only workflows entered in dialog boxes are entered by default
        workflow.set_user_input({input_event.message.get('node_id'): {"user_input": question}})
        workflow.set_workflow_status(WorkflowStatus.INPUT_OVER.value)
        worker_node = workflow_stateful_worker.find_task_node_sync(hash_key)
        continue_workflow.apply_async([unique_id, workflow_id, chat_id, user_id], queue=worker_node)
        events = []
        for event in workflow.sync_get_response_until_break():
            events.append(event)
        status_info = workflow.get_workflow_status()
        if status_info['status'] == WorkflowStatus.FAILED.value:
            raise Exception(status_info.get("reason", "workflow run failed"))
        elif status_info['status'] in [WorkflowStatus.SUCCESS.value, WorkflowStatus.INPUT.value]:
            workflow.set_workflow_stop()
            # Get the content of the first output event as an answer, if not, report an error
            if not events:
                raise Exception("Only Q&A type workflows are currently supported")
            answer = None
            for event in events:
                if event.category in [WorkflowEventType.OutputMsg.value, WorkflowEventType.OutputWithInput.value,
                                      WorkflowEventType.OutputWithChoose.value]:
                    answer = event.message.get('msg', "")
                    break
                elif event.category == WorkflowEventType.StreamMsg.value and event.type != 'stream':
                    answer = event.message.get('msg', "")
                    break
            if answer is None:
                raise Exception("Only Q&A type workflows are currently supported")
            return answer
        else:
            workflow.set_workflow_stop()
            raise Exception(f"workflow status is unknown: {status_info}")
    else:
        raise Exception(f"workflow status is unknown: {status_info}")


async def add_evaluation_task(evaluation_id: int):
    evaluation = EvaluationDao.get_one_evaluation(evaluation_id=evaluation_id)
    if not evaluation:
        return

    redis_key = EvaluationService.get_redis_key(evaluation_id)
    redis_client = get_redis_client_sync()
    try:
        file_data = EvaluationService.read_csv_file(evaluation.file_path)
        csv_data = EvaluationService.parse_csv(file_data)
        progress_increment = 80 / len(csv_data)
        current_progress = 0

        if evaluation.exec_type == ExecType.FLOW.value:
            flow_version = FlowVersionDao.get_version_by_id(version_id=evaluation.version)
            if not flow_version:
                raise Exception("Flow version not found")
            input_keys = await EvaluationService.get_input_keys(flow_id=evaluation.unique_id,
                                                                version_id=evaluation.version)
            first_key = list(input_keys.keys())[0]

            logger.info(f'evaluation task run flow input_keys: {input_keys} first_key: {first_key}')

            for index, one in enumerate(csv_data):
                input_dict = deepcopy(input_keys)
                input_dict[first_key] = one.get('question')
                flow_index, flow_result = await FlowService.exec_flow_node(
                    inputs=input_dict,
                    tweaks={},
                    index=0,
                    versions=[flow_version])
                one["answer"] = flow_result.get(flow_version.id)
                current_progress += progress_increment
                redis_client.set(redis_key, round(current_progress))

        elif evaluation.exec_type == ExecType.ASSISTANT.value:
            assistant = await AssistantDao.aget_one_assistant(evaluation.unique_id)
            if not assistant:
                raise Exception("Assistant not found")
            gpts_agent = AssistantAgent(assistant_info=assistant, chat_id="", invoke_user_id=evaluation.user_id)
            await gpts_agent.init_assistant()
            for index, one in enumerate(csv_data):
                messages = await gpts_agent.run(one.get('question'))
                if len(messages):
                    one["answer"] = messages[-1].content
                current_progress += progress_increment
                redis_client.set(redis_key, round(current_progress))
        elif evaluation.exec_type == ExecType.WORKFLOW.value:
            workflow_info = FlowVersionDao.get_version_by_id(version_id=evaluation.version)
            if not workflow_info or workflow_info.flow_id != evaluation.unique_id:
                raise Exception("workflow version info not found")
            for index, one in enumerate(csv_data):
                one["answer"] = await asyncio.to_thread(execute_workflow_get_answer, workflow_info, evaluation,
                                                        one.get('question', ""))

        _llm = await LLMService.get_evaluation_llm_object(evaluation.user_id)
        llm = LangchainLLM(_llm)
        data_samples = {
            "question": [one.get('question') for one in csv_data],
            "answer": [one.get('answer') for one in csv_data],
            "ground_truths": [[one.get('ground_truth')] for one in csv_data]
        }

        dataset = Dataset.from_dict(data_samples)
        answer_correctness_bisheng = AnswerCorrectnessBisheng(llm=llm, human_prompt=evaluation.prompt)
        score = await asyncio.to_thread(evaluate, dataset, [answer_correctness_bisheng])
        df = score.to_pandas()
        result = df.to_dict(orient="list")
        logger.debug(f'evaluation id = {evaluation_id} result: {result}')

        question = result.get('question', [])
        columns = [
            # Data field:Title:Type(1:Text 2:Numbers 3:%)
            ("question", "question", 1),
            ("ground_truths", "ground_truth", 1),
            ("answer", "answer", 1),
            ("statements_num_gt_only", "statements_num_gt_only", 2),
            ("statements_num_answer_only", "statements_num_answer_only", 2),
            ("statements_num_overlap", "statements_num_overlap", 2),
            ("answer_recall", "recall", 3),
            ("answer_precision", "precision", 3),
            ("answer_f1", "F1", 3)
        ]
        row_list = []
        tmp_dict = defaultdict(int)
        total_dict = {}

        for index, one in enumerate(question):
            row_data = {}
            for field, title, unit_type in columns:
                value = result.get(field)[index]
                if unit_type != 1:
                    tmp_dict[field] += value
                if unit_type == 3:
                    value = f'{value * 100:.2f}%' if value not in ["nan", np.nan] else value
                row_data[title] = value
            row_list.append(row_data)

        total_row_data = {}
        for field, title, unit_type in columns:
            value = tmp_dict.get(field)
            if unit_type == 3:
                value = f'{(value / len(row_list)) * 100:.2f}%'
                total_dict[field] = value
            total_row_data[title] = value
        row_list.append(total_row_data)

        df = pd.DataFrame(data=row_list, columns=[one[1] for one in columns])
        result_file_path = EvaluationService.upload_result_file(df)

        evaluation.result_score = total_dict
        evaluation.status = EvaluationTaskStatus.success.value
        evaluation.result_file_path = result_file_path
        EvaluationDao.update_evaluation(evaluation=evaluation)
        redis_client.delete(redis_key)
        logger.info(f'evaluation task success id={evaluation_id}')

    except Exception as e:
        logger.exception(f'evaluation task failed id={evaluation_id} {str(e)}')
        evaluation.status = EvaluationTaskStatus.failed.value
        evaluation.description = str(e)[-500:]  # Limit the length of the error description to avoid being too long
        EvaluationDao.update_evaluation(evaluation=evaluation)
        redis_client.delete(redis_key)
