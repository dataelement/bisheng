import asyncio
import json
from datetime import datetime
from uuid import uuid4

from bisheng.api.services import knowledge_imp
from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.user_service import UserPayload, get_admin_user, get_login_user
from bisheng.api.services.workstation import (SSECallbackClient, WorkstationConversation,
                                              WorkstationMessage, WorkStationService)
from bisheng.api.v1.callback import AsyncStreamingLLMCallbackHandler
from bisheng.api.v1.schema.chat_schema import APIChatCompletion, SSEResponse, delta
from bisheng.api.v1.schemas import UnifiedResponseModel, WorkstationConfig, resp_200, resp_500
from bisheng.cache.redis import redis_client
from bisheng.cache.utils import save_download_file
from bisheng.database.models.flow import FlowType
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.interface.llms.custom import BishengLLM
from bisheng_langchain.gpts.load_tools import load_tools
from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Request, UploadFile
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger

router = APIRouter(prefix='/workstation', tags=['WorkStation'])

titleInstruction = 'a concise, 5-word-or-less title for the conversation, using its same language, with no punctuation. Apply title case conventions appropriate for the language. Never directly mention the language name or the word "title"'  # noqa
promptSearch = '用户的问题是：%s \
判断用户的问题是否需要联网搜索，如果需要返回数字1，如果不需要返回数字0。只返回1或0，不要返回其他信息。\
如果问题涉及到实时信息、最新事件或特定数据库查询等超出你知识截止日期（2024年7月）的内容，就需要进行联网搜索来获取最新信息。'


# 自定义 JSON 序列化器
def custom_json_serializer(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()  # 转换为 ISO 8601 格式字符串
    raise TypeError(f'Type {type(obj)} not serializable')


def user_message(msgId, conversationId, sender, text):
    msg = json.dumps({
        'message': {
            'messageId': msgId,
            'conversationId': conversationId,
            'sender': sender,
            'text': text
        }
    })
    return f'event: message\ndata: {msg}\n\n'


def step_message(stepId, runId, msgId):
    msg = json.dumps({
        'event': 'on_run_step',
        'data': {
            'id': stepId,
            'runId': runId,
            'type': 'message_creation',
            'index': 0,
            'stepDetails': {
                'type': 'message_creation',
                'message_creation': {
                    'message_id': msgId
                }
            }
        }
    })
    return f'event: message\ndata: {msg}\n\n'


def final_message(conversation, title, requestMessage, responseMessage):
    msg = json.dumps(
        {
            'final': True,
            'conversation': WorkstationConversation.from_chat_session(conversation).model_dump(),
            'title': title,
            'requestMessage': WorkstationMessage.from_chat_message(requestMessage).model_dump(),
            'responseMessage': WorkstationMessage.from_chat_message(responseMessage).model_dump(),
        },
        default=custom_json_serializer)
    return f'event: message\ndata: {msg}\n\n'


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
    file_byte = await file.read()
    file_path = save_download_file(file_byte, 'bisheng', file.filename)
    res = await WorkStationService.uploadPersonalKnowledge(request,
                                                           login_user,
                                                           file_path=file_path,
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


@router.post('/files')
async def upload_file(
        request: Request,
        file: UploadFile = File(...),
        login_user: UserPayload = Depends(get_login_user),
):
    """
    上传文件
    """
    # 读取文件内容
    file_content = await file.read()
    bytes_length = len(file_content)
    filename = file.filename

    # 保存文件
    file_path = save_download_file(file_content, 'bisheng', file.filename)

    # 返回文件路径
    return resp_200(
        data={
            'filepath': file_path,
            'bytes': bytes_length,
            'filename': filename,
            'type': file.content_type,
            'user': login_user.user_id,
            '_id': uuid4().hex,
            'createdAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'updatedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'temp_file_id': uuid4().hex,
            'file_id': uuid4().hex,
            'message': 'File uploaded successfully',
            'context': 'message_attachment',
        })


@router.post('/gen_title')
async def gen_title(conversationId: str = Body(..., description='', embed=True),
                    login_user: UserPayload = Depends(get_login_user)):
    """
    生成标题
    """
    # 获取会话消息
    redis_key = f'workstation_title_{conversationId}'
    title = redis_client.get(redis_key)
    if not title:
        await asyncio.sleep(5)
        # 如果标题已经存在，则直接返回
        title = redis_client.get(redis_key)
    if title:
        # 如果标题已经存在，则直接返回
        redis_client.delete(redis_key)
        return resp_200({'title': title})
    else:
        # 如果标题不存在，则返回空值
        return resp_500(
            "Title not found or method not implemented for the conversation\'s endpoint")


@router.get('/messages/{conversationId}')
def get_chat_history(conversationId: str):
    messages = ChatMessageDao.get_messages_by_chat_id(chat_id=conversationId, limit=1000)
    if messages:
        return resp_200([WorkstationMessage.from_chat_message(message) for message in messages])
    else:
        return resp_200([])


async def genTitle(human: str, assistant: str, llm: BishengLLM, conversationId: str):
    """
    生成标题
    """
    convo = f'||>User:\n"{human}"\n ||>Response:\n"{assistant}"'
    prompt = f'Please generate {titleInstruction} \n{convo} \n||>Title:'
    logger.info(f'convo: {convo}')
    res = llm.invoke(prompt)
    title = res.content
    redis_client.set(f'workstation_title_{conversationId}', title)
    session = MessageSessionDao.get_one(conversationId)
    if session:
        session.flow_name = title
        MessageSessionDao.insert_one(session)


async def webSearch(query: str, bingKey: str, bingUrl: str):
    """
    联网搜索
    """
    bingtool = load_tools(tool_params={
        'bing_search': {
            'bing_subscription_key': bingKey,
            'bing_search_url': bingUrl,
        }
    })[0]
    res = await bingtool.ainvoke({'query': query})
    search_res = ''
    web_list = []
    for index, result in enumerate(res):
        # 处理搜索结果
        snippet = result.get('snippet')
        search_res += f'[webpage ${index} begin]\n${snippet}\n[webpage ${index} end]\n\n'
        web_list.append({
            'title': result.get('title'),
            'url': result.get('link'),
            'snippet': snippet
        })
    return search_res, web_list


def getFileContent(filepath, filename):
    #  获取文件全文
    raw_texts, _, _, _ = knowledge_imp.read_chunk_text(
        filepath,
        filename,
        ['\n\n\n\n\n'],
        [],
        102400,
        0,
    )
    return knowledge_imp.KnowledgeUtils.chunk2promt(''.join(raw_texts), {'source': filename})


@router.post('/chat/completions')
async def chat_completions(
        data: APIChatCompletion,
        login_user: UserPayload = Depends(get_login_user),
):
    wsConfig = WorkStationService.get_config()
    conversationId = data.conversationId

    # 如果没有传入会话ID，则使用默认的会话ID
    if not conversationId:
        conversationId = uuid4().hex
        MessageSessionDao.insert_one(
            MessageSession(
                chat_id=conversationId,
                flow_id='',
                flow_name='New Chat',
                flow_type=FlowType.WORKSTATION.value,
                user_id=login_user.user_id,
            ))

    conversaiton = MessageSessionDao.get_one(conversationId)
    message = ChatMessageDao.insert_one(
        ChatMessage(
            user_id=login_user.user_id,
            chat_id=conversationId,
            flow_id='',
            type='human',
            is_bot=False,
            sender='User',
            extra=json.dumps({'parentMessageId': data.parentMessageId}),
            message=data.text,
            category='question',
            source=0,
        ))

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
    async def event_stream():
        prompt = data.text
        if data.search_enabled:
            # 如果开启搜索，先检查prompt 是否需要搜索
            stepId = f'step_${uuid4().hex}'
            yield step_message(stepId, uuid4().hex, f'msg_{uuid4().hex}')
            searchTExt = promptSearch % data.text
            inputs = [HumanMessage(content=searchTExt)]
            searchRes = await bishengllm.ainvoke(searchTExt)
            if searchRes.content == '1':
                # 如果需要联网搜索，则调用搜索接口
                search_res, web_list = await webSearch(data.text, wsConfig.bing_subscription_key,
                                                       wsConfig.bing_search_url)
                content = {'content': [{'type': 'search_result', 'search_result': web_list}]}
                yield SSEResponse(event='on_search_result', data=delta(id=stepId,
                                                                       delta=content)).toString()
                prompt = wsConfig.webSearch.prompt.format(
                    search_results=search_res,
                    cur_date=datetime.now().strftime('%Y-%m-%d'),
                    question=data.text)
        elif data.knowledge_enabled:
            chunks = WorkStationService.queryChunksFromDB(data.text, login_user)
            prompt = wsConfig.knowledgeBase.prompt.format(content='\n'.join(chunks),
                                                          question=data.text)

        if data.files:
            #  获取文件全文
            filecontent = '\n'.join([
                getFileContent(file.get('filepath'), file.get('filename')) for file in data.files
            ])
            prompt = wsConfig.fileUpload.prompt.format(content=filecontent, question=data.text)
        yield user_message(message.id, conversationId, 'User', data.text)

        inputs = [HumanMessage(content=prompt)]
        task = asyncio.create_task(
            bishengllm.ainvoke(
                inputs,
                config=RunnableConfig(callbacks=[callbackHandler]),
            ))
        final_res = ''
        resoning_res = ''
        stepId = None
        # 消息存储
        # 处理流式输出
        needBreak = False
        while True:
            try:
                token = SSEClient.queue.get_nowait()
                content = token.get('message').get('content')
                reasoning_content = token.get('message').get('reasoning_content')
                if content:
                    if not final_res:
                        # 第一次返回的消息
                        stepId = 'step_' + uuid4().hex
                        yield step_message(stepId, uuid4().hex, f'msg_{uuid4().hex}')
                    final_res += content
                    content = {'content': [{'type': 'text', 'text': content}]}
                    yield SSEResponse(event='on_message_delta',
                                      data=delta(id=stepId, delta=content)).toString()

                elif reasoning_content:
                    if not resoning_res:
                        # 第一次返回的消息
                        stepId = 'step_' + uuid4().hex
                        yield step_message(stepId, uuid4().hex, f'msg_{uuid4().hex}')
                    resoning_res += reasoning_content
                    content = {'type': 'think', 'think': reasoning_content}
                    yield SSEResponse(event='on_reasoning_delta',
                                      data=delta(id=stepId, delta=content)).toString()
            except asyncio.QueueEmpty:
                if needBreak:
                    break
                await asyncio.sleep(0.3)  # 等待一段时间再继续检查队列

            # 循环获取task 结果，不等待
            try:
                if task.done():
                    final_res = task.result()  # Raise any exception if the task failed
                    needBreak = True
            except Exception as e:
                logger.error(f'Error in task: {e}')
                break
        # 结束流式输出
        final_res = ''':::thinking\n''' + resoning_res + '''\n:::''' + final_res.content if resoning_res else final_res.content  # noqa
        responseMessage = ChatMessageDao.insert_one(
            ChatMessage(
                user_id=login_user.user_id,
                chat_id=conversationId,
                flow_id='',
                type='assistant',
                is_bot=True,
                message=final_res,
                category='answer',
                sender=bishengllm.model_name,
                extra=json.dumps({'parentMessageId': message.id}),
                source=0,
            ))
        yield final_message(conversaiton, conversaiton.flow_name, message, responseMessage)

        if not data.conversationId:
            # 生成title
            asyncio.create_task(genTitle(data.text, final_res, bishengllm, conversationId))

    return StreamingResponse(event_stream(), media_type='text/event-stream')
