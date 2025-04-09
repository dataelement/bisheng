import asyncio
import json

from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.user_service import UserPayload, get_admin_user, get_login_user
from bisheng.api.services.workstation import SSECallbackClient, WorkStationService
from bisheng.api.v1.callback import AsyncStreamingLLMCallbackHandler
from bisheng.api.v1.schema.chat_schema import APIChatCompletion, SSEResponse, delta
from bisheng.api.v1.schemas import UnifiedResponseModel, WorkstationConfig, resp_200
from bisheng.interface.llms.custom import BishengLLM
from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Request, UploadFile
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger

router = APIRouter(prefix='/workstation', tags=['WorkStation'])


@router.get('/config', response_model=UnifiedResponseModel[WorkstationConfig])
def get_config(
    request: Request,
    login_user: UserPayload = Depends(get_login_user),
) -> UnifiedResponseModel[WorkstationConfig]:
    """ 获取评价相关的模型配置 """
    ret = WorkStationService.get_config()
    return resp_200(data=ret)


@router.post('/config', response_model=UnifiedResponseModel[WorkstationConfig])
def update_config(
    request: Request,
    login_user: UserPayload = Depends(get_admin_user),
    data: WorkstationConfig = Body(..., description='默认模型配置'),
) -> UnifiedResponseModel[WorkstationConfig]:
    """ 更新评价相关的模型配置 """
    ret = WorkStationService.update_config(request, login_user, data)
    return resp_200(data=ret)


@router.post('/knowledgeUpload')
async def knowledgeUpload(request: Request,
                          background_tasks: BackgroundTasks,
                          file: UploadFile = File(...),
                          login_user: UserPayload = Depends(get_login_user)):
    res = WorkStationService.uploadPersonalKnowledge(request,
                                                     login_user,
                                                     file_path=file.filename,
                                                     background_tasks=background_tasks)
    return resp_200(data=res[0])


@router.get('/queryKnowledge')
def queryKnoledgeList(request: Request,
                      page: int,
                      size: int,
                      login_user: UserPayload = Depends(get_login_user)):
    # 查询是否有个人知识库
    res, total = WorkStationService.queryKnowledgeList(request, login_user, page, size)
    return resp_200(data={'list': res, 'total': total})


@router.delete('/deleteKnowledge')
def deleteKnowledge(request: Request,
                    file_id: int,
                    login_user: UserPayload = Depends(get_login_user)):
    res = KnowledgeService.delete_knowledge_file(request, login_user, [file_id])
    return resp_200(data=res)


@router.post('/chat/completions')
async def chat_completions(
        data: APIChatCompletion,
        login_user: UserPayload = Depends(get_login_user),
):
    # 掉用bishengllm 实现sse 返回
    bishengllm = BishengLLM(model_id=data.model)

    # 模型掉用实现流式输出
    SSEClient = SSECallbackClient()
    callbackHandler = AsyncStreamingLLMCallbackHandler(
        websocket=SSEClient,
        flow_id='',
        chat_id=data.conversationId,
        user_id=login_user.user_id,
    )

    # 处理流式输出
    inputs = [HumanMessage(content=data.text)]

    task = asyncio.create_task(
        bishengllm.ainvoke(
            inputs,
            config=RunnableConfig(callbacks=[callbackHandler]),
        ))

    async def event_stream():
        final_res = ''
        # 消息存储
        # 处理流式输出
        needBreak = False
        while True:
            try:
                token = SSEClient.queue.get_nowait()
                content = token.get('content')
                reasoning_content = token.get('reasoning_content')
                if content:
                    content = {'content': [{'type': 'text', 'text': content}]}
                    yield 'event: message\n'
                    yield SSEResponse(event='on_message_delta',
                                      data=delta(id=data.conversationId, delta=content))
                    yield '\n\n'
                elif reasoning_content:
                    content = {'type': 'think', 'think': reasoning_content}
                    yield 'event: message\n'
                    yield SSEResponse(event='on_reasoning_delta',
                                      data=delta(id=data.conversationId, delta=content))
                    yield '\n\n'
            except asyncio.QueueEmpty:
                if needBreak:
                    break
                await asyncio.sleep(1)

            # 循环获取task 结果，不等待
            try:
                if task.done():
                    final_res = task.result()  # Raise any exception if the task failed
                    needBreak = True
            except Exception as e:
                logger.error(f'Error in task: {e}')
                break
        # 结束流式输出
        final_res = ''':::thinking\n'''
        yield 'event: message\n'
        yield json.dumps({
            'final': True,
            'conversation': '',
            'title': 'New Chat',
            'requestMessage': '',
            'responseMessage': final_res
        })
        yield '\n\n'

    return StreamingResponse(event_stream(), media_type='text/event-stream')
