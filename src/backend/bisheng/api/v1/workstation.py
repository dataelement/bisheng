import asyncio
import json
from datetime import datetime
from urllib.parse import unquote
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Request, UploadFile
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger

from bisheng.api.services import knowledge_imp
from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.user_service import UserPayload, get_admin_user, get_login_user
from bisheng.api.services.workstation import (SSECallbackClient, WorkstationConversation,
                                              WorkstationMessage, WorkStationService, SearchTool)
from bisheng.api.v1.callback import AsyncStreamingLLMCallbackHandler
from bisheng.api.v1.schema.chat_schema import APIChatCompletion, SSEResponse, delta
from bisheng.api.v1.schemas import WorkstationConfig, resp_200, resp_500, WSPrompt, ExcelRule
from bisheng.cache.redis import redis_client
from bisheng.cache.utils import file_download, save_download_file, save_uploaded_file
from bisheng.database.models.flow import FlowType
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.interface.llms.custom import BishengLLM

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
        },
        'created': True
    })
    return f'event: message\ndata: {msg}\n\n'


def step_message(stepId, runId, index, msgId):
    msg = json.dumps({
        'event': 'on_run_step',
        'data': {
            'id': stepId,
            'runId': runId,
            'type': 'message_creation',
            'index': index,
            'stepDetails': {
                'type': 'message_creation',
                'message_creation': {
                    'message_id': msgId
                }
            }
        }
    })
    return f'event: message\ndata: {msg}\n\n'


def final_message(conversation: MessageSession, title: str, requestMessage: ChatMessage, text: str,
                  error: bool, modelName: str):
    responseMessage = ChatMessageDao.insert_one(
        ChatMessage(
            user_id=conversation.user_id,
            chat_id=conversation.chat_id,
            flow_id='',
            type='assistant',
            is_bot=True,
            message=text,
            category='answer',
            sender=modelName,
            extra=json.dumps({
                'parentMessageId': requestMessage.id,
                'error': error
            }),
            source=0,
        ))
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


@router.get('/config')
def get_config(
        request: Request,
        login_user: UserPayload = Depends(get_login_user),
):
    """ 获取评价相关的模型配置 """
    ret = WorkStationService.get_config()
    return resp_200(data=ret)


@router.post('/config')
def update_config(
        request: Request,
        login_user: UserPayload = Depends(get_admin_user),
        data: WorkstationConfig = Body(..., description='默认模型配置'),
):
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
        file_id: str = Body(..., description='文件ID'),
        login_user: UserPayload = Depends(get_login_user),
):
    """
    上传文件
    """
    # 读取文件内容
    # 保存文件
    file_path = save_uploaded_file(file.file, 'bisheng', unquote(file.filename))

    # 返回文件路径
    return resp_200(
        data={
            'filepath': file_path,
            'filename': unquote(file.filename),
            'type': file.content_type,
            'user': login_user.user_id,
            '_id': uuid4().hex,
            'createdAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'updatedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'temp_file_id': file_id,
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
            data="Title not found or method not implemented for the conversation\'s endpoint")


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


async def webSearch(query: str, web_search_config: WSPrompt):
    """
    联网搜索
    """
    if web_search_config.params:
        tool = SearchTool.init_search_tool(web_search_config.tool, **web_search_config.params)
    else:
        # 兼容旧版的配置
        tool = SearchTool.init_search_tool('bing', api_key=web_search_config.bingKey,
                                           base_url=web_search_config.bingUrl)
    return tool.invoke(query)


def getFileContent(filepath):
    """
    获取文件内容
    """
    filepath_local, file_name = file_download(filepath)
    raw_texts, _, _, _ = knowledge_imp.read_chunk_text(
        filepath_local,
        file_name,
        ['\n\n', '\n'],
        ['after', 'after'],
        1000,
        0,
        excel_rule=ExcelRule()
    )
    return knowledge_imp.KnowledgeUtils.chunk2promt(''.join(raw_texts), {'source': file_name})


@router.post('/chat/completions')
async def chat_completions(
        data: APIChatCompletion,
        login_user: UserPayload = Depends(get_login_user),
):
    wsConfig = WorkStationService.get_config()
    conversationId = data.conversationId
    model = [model for model in wsConfig.models if model.id == data.model][0]
    modelName = model.displayName

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
    if conversaiton is None:
        return resp_500('会话不存在')

    if data.overrideParentMessageId:
        message = ChatMessageDao.get_message_by_id(data.overrideParentMessageId)
    else:
        message = ChatMessageDao.insert_one(
            ChatMessage(
                user_id=login_user.user_id,
                chat_id=conversationId,
                flow_id='',
                type='human',
                is_bot=False,
                sender='User',
                files=json.dumps(data.files) if data.files else None,
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
        yield user_message(message.id, conversationId, 'User', data.text)
        prompt = data.text
        web_list = []
        error = False
        final_res = ''
        final_result = None
        resoning_res = ''
        # prompt 长度token截断
        max_token = wsConfig.maxTokens
        runId = uuid4().hex
        index = 0

        try:
            if data.search_enabled:
                # 如果开启搜索，先检查prompt 是否需要搜索
                stepId = f'step_${uuid4().hex}'
                yield step_message(stepId, runId, index, f'msg_{uuid4().hex}')
                index += 1
                searchTExt = promptSearch % data.text
                inputs = [HumanMessage(content=searchTExt)]
                searchRes = await bishengllm.ainvoke(searchTExt)
                if searchRes.content == '1':
                    logger.info(f'需要联网搜索, prompt={data.text}')
                    # 如果需要联网搜索，则调用搜索接口
                    search_res, web_list = await webSearch(data.text, wsConfig.webSearch)
                    content = {'content': [{'type': 'search_result', 'search_result': web_list}]}
                    yield SSEResponse(event='on_search_result',
                                      data=delta(id=stepId, delta=content)).toString()
                    prompt = wsConfig.webSearch.prompt.format(
                        search_results=search_res[:max_token],
                        cur_date=datetime.now().strftime('%Y-%m-%d'),
                        question=data.text)
            elif data.knowledge_enabled:
                logger.info(f'knowledge, prompt={data.text}')
                chunks = WorkStationService.queryChunksFromDB(data.text, login_user)
                prompt = wsConfig.knowledgeBase.prompt.format(
                    retrieved_file_content='\n'.join(chunks)[:max_token], question=data.text)
            elif data.files:
                #  获取文件全文
                filecontent = '\n'.join(
                    [getFileContent(file.get('filepath')) for file in data.files])
                prompt = wsConfig.fileUpload.prompt.format(file_content=filecontent[:max_token],
                                                           question=data.text)
            if prompt != data.text:
                # 需要将原始消息存储
                extra = json.loads(message.extra)
                extra['prompt'] = prompt
                message.extra = json.dumps(extra, ensure_ascii=False)
                ChatMessageDao.insert_one(message)
        except Exception as e:
            logger.error(f'Error in processing the prompt: {e}')
            error = True
            final_res = 'Error in processing the prompt'

        if not error:
            messages = WorkStationService.get_chat_history(conversationId, 8)[:-1]
            inputs = [*messages, HumanMessage(content=prompt)]
            if wsConfig.systemPrompt:
                inputs.insert(0, SystemMessage(content=wsConfig.systemPrompt))
            task = asyncio.create_task(
                bishengllm.ainvoke(
                    inputs,
                    config=RunnableConfig(callbacks=[callbackHandler]),
                ))

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
                            yield step_message(stepId, runId, index, f'msg_{uuid4().hex}')
                            index += 1
                        final_res += content
                        content = {'content': [{'type': 'text', 'text': content}]}
                        yield SSEResponse(event='on_message_delta',
                                          data=delta(id=stepId, delta=content)).toString()

                    elif reasoning_content:
                        if not resoning_res:
                            # 第一次返回的消息
                            stepId = 'step_' + uuid4().hex
                            yield step_message(stepId, runId, index, f'msg_{uuid4().hex}')
                            index += 1
                        resoning_res += reasoning_content
                        content = {'content': [{'type': 'think', 'think': reasoning_content}]}
                        yield SSEResponse(event='on_reasoning_delta',
                                          data=delta(id=stepId, delta=content)).toString()
                except asyncio.QueueEmpty:
                    if needBreak:
                        break
                    await asyncio.sleep(0.3)  # 等待一段时间再继续检查队列
                except Exception as e:
                    logger.error(f'Error in processing the message: {e}')
                    error = True
                    break

                # 循环获取task 结果，不等待
                try:
                    if task.done():
                        final_result = task.result()  # Raise any exception if the task failed
                        needBreak = True
                except Exception as e:
                    logger.error(f'Error in task: {e}')
                    break
        # 结束流式输出
        if resoning_res:
            final_res = ''':::thinking\n''' + resoning_res + '''\n:::''' + final_result.content
        elif web_list:
            final_res = ''':::web\n''' + json.dumps(
                web_list, ensure_ascii=False) + '''\n:::''' + final_result.content
        else:
            final_res = final_result.content if final_result else final_res

        yield final_message(conversaiton, conversaiton.flow_name, message, final_res, error,
                            modelName)

        if not data.conversationId:
            # 生成title
            asyncio.create_task(genTitle(data.text, final_res, bishengllm, conversationId))

    return StreamingResponse(event_stream(), media_type='text/event-stream')
