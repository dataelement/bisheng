import asyncio
import json
from collections import defaultdict
from typing import Any, Dict, List
from uuid import UUID

from bisheng.api.utils import build_flow_no_yield
from bisheng.api.v1.schemas import ChatMessage, ChatResponse, FileResponse
from bisheng.cache import cache_manager
from bisheng.cache.flow import InMemoryCache
from bisheng.cache.manager import Subject
from bisheng.chat.utils import extract_answer_keys, process_graph
from bisheng.database.base import get_session
from bisheng.database.models.flow import Flow
from bisheng.database.models.model_deploy import ModelDeploy
from bisheng.database.models.recall_chunk import RecallChunk
from bisheng.utils.logger import logger
from bisheng.utils.util import get_cache_key
from bisheng_langchain.chains.autogen.auto_gen import AutoGenChain
from fastapi import WebSocket, status
from langchain.docstore.document import Document
from sqlmodel import select


class ChatHistory(Subject):

    def __init__(self):
        super().__init__()
        self.history: Dict[str, List[ChatMessage]] = defaultdict(list)

    def add_message(self, client_id: str, chat_id: str, message: ChatMessage):
        """Add a message to the chat history."""

        if chat_id and (message.message or message.intermediate_steps or
                        message.files) and message.type != 'stream':
            with next(get_session()) as seesion:
                from bisheng.database.models.message import ChatMessage
                msg = message.copy()
                msg.message = str(msg.message) if isinstance(msg.message, dict) else msg.message
                files = json.dumps(msg.files) if msg.files else ''
                msg.__dict__.pop('files')
                db_message = ChatMessage(flow_id=client_id,
                                         chat_id=chat_id,
                                         files=files,
                                         **msg.__dict__)
                logger.info(f'chat={db_message}')
                seesion.add(db_message)
                seesion.commit()
                seesion.refresh(db_message)
                message.message_id = db_message.id

        if not isinstance(message, FileResponse):
            self.notify()

    def empty_history(self, client_id: str, chat_id: str):
        """Empty the chat history for a client."""
        self.history[get_cache_key(client_id, chat_id)] = []


class ChatManager:

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.chat_history = ChatHistory()
        self.cache_manager = cache_manager
        self.cache_manager.attach(self.update)
        self.in_memory_cache = InMemoryCache()

    # def on_chat_history_update(self):
    #     """Send the last chat message to the client."""
    #     client_id = self.cache_manager.current_client_id
    #     if client_id in self.active_connections:
    #         chat_response = self.chat_history.get_history(client_id, filter_messages=False)[-1]
    #         if chat_response.is_bot:
    #             # Process FileResponse
    #             if isinstance(chat_response, FileResponse):
    #                 # If data_type is pandas, convert to csv
    #                 if chat_response.data_type == 'pandas':
    #                     chat_response.data = chat_response.data.to_csv()
    #                 elif chat_response.data_type == 'image':
    #                     # Base64 encode the image
    #                     chat_response.data = pil_to_base64(chat_response.data)
    #             # get event loop
    #             loop = asyncio.get_event_loop()

    #             coroutine = self.send_json(client_id, chat_response)
    #             asyncio.run_coroutine_threadsafe(coroutine, loop)

    def update(self):
        if self.cache_manager.current_client_id in self.active_connections:
            self.last_cached_object_dict = self.cache_manager.get_last()
            # Add a new ChatResponse with the data
            chat_response = FileResponse(
                message=None,
                type='file',
                data=self.last_cached_object_dict['obj'],
                data_type=self.last_cached_object_dict['type'],
            )

            self.chat_history.add_message(self.cache_manager.current_client_id,
                                          self.cache_manager.current_chat_id, chat_response)

    async def connect(self, client_id: str, chat_id: str, websocket: WebSocket):
        await websocket.accept()

        self.active_connections[get_cache_key(client_id, chat_id)] = websocket

    def disconnect(self, client_id: str, chat_id: str):
        self.active_connections.pop(get_cache_key(client_id, chat_id), None)

    async def send_message(self, client_id: str, chat_id: str, message: str):
        websocket = self.active_connections[get_cache_key(client_id, chat_id)]
        await websocket.send_text(message)

    async def send_json(self, client_id: str, chat_id: str, message: ChatMessage, add=True):
        websocket = self.active_connections[get_cache_key(client_id, chat_id)]
        # 增加消息记录
        if add:
            self.chat_history.add_message(client_id, chat_id, message)
        await websocket.send_json(message.dict())

    async def close_connection(self, client_id: str, chat_id: str, code: int, reason: str):
        if websocket := self.active_connections[get_cache_key(client_id, chat_id)]:
            try:
                await websocket.close(code=code, reason=reason)
                self.disconnect(client_id, chat_id)
            except RuntimeError as exc:
                # This is to catch the following error:
                #  Unexpected ASGI message 'websocket.close', after sending 'websocket.close'
                if 'after sending' in str(exc):
                    logger.error(exc)

    async def ping(self, client_id: str, chat_id: str):
        ping_pong = ChatMessage(
            is_bot=True,
            message='pong',
            intermediate_steps='',
        )
        await self.send_json(client_id, chat_id, ping_pong, False)

    async def dispatch_task(self, client_id: str, chat_id: str, payload: dict, user_id):
        with self.cache_manager.set_client_id(client_id, chat_id):
            if 'action' in payload:
                await self.process_autogen(client_id, chat_id, payload)
            elif 'file_path' in payload:
                # 上传文件，需要处理文件逻辑
                file_path = payload.get('file_path')
                node_id = payload.get('id')
                logger.info(f'client_id={client_id} act=process_message user_id={chat_id}')
                await self.process_file(file_path=file_path,
                                        chat_id=chat_id,
                                        client_id=client_id,
                                        id=node_id,
                                        user_id=user_id)
            else:
                logger.info(f'client_id={client_id} act=process_message user_id={chat_id}')
                await self.process_message(client_id, chat_id, payload, None, False, user_id)

    async def process_autogen(self, client_id: str, chat_id: str, data: dict):
        key = get_cache_key(client_id, chat_id)
        langchain_object = self.in_memory_cache.get(key)
        logger.info(f'reciever_human_interactive langchain={langchain_object}')
        action = data.get('action')
        if action.lower() == 'stop':
            if hasattr(langchain_object, 'stop'):
                logger.info('reciever_human_interactive langchain_objct')
                await langchain_object.stop()
            else:
                logger.error(f'act=auto_gen act={action}')
        elif action.lower() == 'continue':
            # autgen_user 对话的时候，进程 wait() 需要换新
            if hasattr(langchain_object, 'input'):
                await langchain_object.input(data.get('inputs'))
                # 新的对话开始，
                start_resp = ChatResponse(type='start')
                await self.send_json(client_id, chat_id, start_resp)
            else:
                logger.error(f'act=auto_gen act={action}')

    async def process_file(self, client_id: str, chat_id: str, user_id: int, file_path: str,
                           id: str):
        """upload file to make flow work"""
        db_flow = next(get_session()).get(Flow, client_id)
        graph_data = db_flow.data
        file_path, file_name = file_path.split('_', 1)
        for node in graph_data['nodes']:
            if node.get('id') == id:
                for key, value in node['data']['node']['template'].items():
                    if isinstance(value, dict) and value.get('type') == 'file':
                        logger.info(f'key={key} set_filepath={file_path}')
                        value['file_path'] = file_path
                        value['value'] = file_name

        # 如果L3
        file = ChatMessage(is_bot=False,
                           files=[{'file_name': file_name}],
                           type='end',
                           user_id=user_id)
        self.chat_history.add_message(client_id, chat_id, file)
        # graph_data = payload
        start_resp = ChatResponse(type='begin', category='system', user_id=user_id)
        await self.send_json(client_id, chat_id, start_resp)
        start_resp.type = 'start'
        await self.send_json(client_id, chat_id, start_resp)

        # build to activate node
        artifacts = {}
        try:
            graph = build_flow_no_yield(graph_data, artifacts, True, UUID(client_id).hex, chat_id)
        except Exception as e:
            logger.exception(e)
            step_resp = ChatResponse(type='end',
                                     intermediate_steps='File is parsed fail',
                                     category='system',
                                     user_id=user_id)
            await self.send_json(client_id, chat_id, step_resp)
            start_resp.type = 'close'
            await self.send_json(client_id, chat_id, start_resp)
            return
        # 更新langchainObject
        langchain_object = graph.build()
        for node in langchain_object:
            key_node = get_cache_key(client_id, chat_id, node.id)
            self.set_cache(key_node, node._built_object)
            self.set_cache(key_node + '_artifacts', artifacts)
            self.set_cache(get_cache_key(client_id, chat_id), node._built_object)
        # 查找nodeid关联的questions
        input = next((node for node in graph.nodes if node.vertex_type == 'InputNode'), None)
        if not input:
            step_resp = ChatResponse(type='end',
                                     intermediate_steps='File parsing complete',
                                     category='system',
                                     user_id=user_id)
            await self.send_json(client_id, chat_id, step_resp)
            start_resp.type = 'close'
            await self.send_json(client_id, chat_id, start_resp)
            return
        questions = input._built_object
        step_resp = ChatResponse(type='end',
                                 intermediate_steps='File parsing complete, analysis starting',
                                 category='system',
                                 user_id=user_id)
        await self.send_json(client_id, chat_id, step_resp)

        edge = input.edges[0]
        input_key = edge.target._built_object.input_keys[0]

        report = ''
        for question in questions:
            if not question:
                continue
            payload = {'inputs': {input_key: question, 'id': edge.target.id}}
            start_resp.category == 'question'
            await self.send_json(client_id, chat_id, start_resp)
            step_resp = ChatResponse(type='end',
                                     intermediate_steps=question,
                                     category='question',
                                     user_id=user_id)
            await self.send_json(client_id, chat_id, step_resp)
            result = await self.process_message(client_id, chat_id, payload, None, True, user_id)
            report = f"""{report}### {question} \n {result} \n """

        start_resp.category = 'report'
        await self.send_json(client_id, chat_id, start_resp)
        response = ChatResponse(type='end',
                                intermediate_steps=report,
                                category='report',
                                user_id=user_id)
        await self.send_json(client_id, chat_id, response)
        close_resp = ChatResponse(type='close', category='system', user_id=user_id)
        await self.send_json(client_id, chat_id, close_resp)

    async def process_message(self,
                              client_id: str,
                              chat_id: str,
                              payload: Dict,
                              langchain_object: Any,
                              is_bot=False,
                              user_id=None):
        # Process the graph data and chat message
        chat_inputs = payload.pop('inputs', '')
        node_id = chat_inputs.pop('id') if 'id' in chat_inputs else ''
        key = get_cache_key(client_id, chat_id, node_id)
        artifacts = self.in_memory_cache.get(key + '_artifacts')
        if artifacts:
            for k, value in artifacts.items():
                if k in chat_inputs:
                    chat_inputs[k] = value
        chat_inputs = ChatMessage(message=chat_inputs, category='question',
                                  is_bot=is_bot, type='bot', user_id=user_id,)
        if not is_bot:
            # 从file auto trigger process_message， the question already saved
            self.chat_history.add_message(client_id, chat_id, chat_inputs)
            start_resp = ChatResponse(type='begin', user_id=user_id)
            await self.send_json(client_id, chat_id, start_resp)
        start_resp = ChatResponse(type='start', user_id=user_id)
        await self.send_json(client_id, chat_id, start_resp)

        # is_first_message = len(self.chat_history.get_history(client_id=client_id)) <= 1
        # Generate result and thought
        try:
            logger.debug(f'Generating result and thought key={key}')
            langchain_object = self.in_memory_cache.get(key)
            result, intermediate_steps, source_doucment = await process_graph(
                langchain_object=langchain_object,
                chat_inputs=chat_inputs,
                websocket=self.active_connections[get_cache_key(client_id, chat_id)],
            )
        except Exception as e:
            # Log stack trace
            logger.exception(e)
            end_resp = ChatResponse(type='end',
                                    intermediate_steps=f'分析出错，{str(e)}',
                                    user_id=user_id)
            await self.send_json(client_id, chat_id, end_resp)
            close_resp = ChatResponse(type='close', user_id=user_id)
            if not chat_id:
                # 技能编排页面， 无法展示intermediate
                await self.send_json(client_id, chat_id, start_resp)
                end_resp.message = end_resp.intermediate_steps
                end_resp.intermediate_steps = None
                await self.send_json(client_id, chat_id, end_resp)
            await self.send_json(client_id, chat_id, close_resp)
            return

        # Send a response back to the frontend, if needed
        intermediate_steps = intermediate_steps or ''
        # history = self.chat_history.get_history(client_id, chat_id, filter_messages=False)
        await self.process_logs(client_id, chat_id, user_id, intermediate_steps)
        source = True if source_doucment and chat_id else False
        if source:
            for doc in source_doucment:
                # 确保每个chunk 都可溯源
                if 'bbox' not in doc.metadata or not doc.metadata['bbox']:
                    source = False
        # 最终结果
        if isinstance(langchain_object, AutoGenChain):
            # 群聊，最后一条消息重复，不进行返回
            start_resp.category = 'divider'
            await self.send_json(client_id, chat_id, start_resp)
            response = ChatResponse(message='本轮结束', type='end',
                                    category='divider', user_id=user_id)
            await self.send_json(client_id, chat_id, response)
        else:
            start_resp.category = 'answer'
            await self.send_json(client_id, chat_id, start_resp)
            response = ChatResponse(message=result if not is_bot else '',
                                    type='end',
                                    intermediate_steps=result if is_bot else '',
                                    category='answer',
                                    user_id=user_id,
                                    source=source)
            await self.send_json(client_id, chat_id, response)

        # 循环结束
        close_resp = ChatResponse(type='close', user_id=user_id)
        await self.send_json(client_id, chat_id, close_resp)

        if source:
            # 处理召回的chunk
            await self.process_source_document(source_doucment, chat_id, response.message_id,
                                               result,)
        return result

    async def process_logs(self, client_id, chat_id, user_id, intermediate_steps):
        end_resp = ChatResponse(type='end', user_id=user_id)
        if not intermediate_steps:
            return await self.send_json(client_id, chat_id, end_resp, add=False)

        # 将最终的分析过程存数据库
        steps = []
        if isinstance(intermediate_steps, list):
            # autogen produce multi dialog
            for message in intermediate_steps:
                content = message.get('message')
                sender = message.get('sender')
                receiver = message.get('receiver')
                is_bot = False if receiver and receiver.get('is_bot') else True
                msg = ChatResponse(message=content, sender=sender, receiver=receiver,
                                   type='end', user_id=user_id, is_bot=is_bot)
                steps.append(msg)
        else:
            # agent model will produce the steps log
            if chat_id and intermediate_steps.strip():
                for s in intermediate_steps.split('\n'):
                    if 'source_documents' in s:
                        answer = eval(s.split(':', 1)[1])
                        if 'result' in answer:
                            s = 'Answer: ' + answer.get('result')
                    msg = ChatResponse(intermediate_steps=s, type='end', user_id=user_id)
                    steps.append(msg)
            else:
                # 只有L3用户给出详细的log
                end_resp.intermediate_steps = intermediate_steps
        await self.send_json(client_id, chat_id, end_resp, add=False)

        for step in steps:
            # save chate message
            self.chat_history.add_message(client_id, chat_id, step)

    def set_cache(self, client_id: str, langchain_object: Any) -> bool:
        """
        Set the cache for a client.
        """

        self.in_memory_cache.set(client_id, langchain_object)
        return client_id in self.in_memory_cache

    async def handle_websocket(self, client_id: str, chat_id: str, websocket: WebSocket,
                               user_id: int):
        await self.connect(client_id, chat_id, websocket)

        try:
            while True:
                json_payload = await websocket.receive_json()
                logger.info(f'receive_message payload={json_payload}')
                try:
                    payload = json.loads(json_payload)
                except TypeError:
                    payload = json_payload
                if 'clear_history' in payload:
                    self.chat_history.history[client_id] = []
                    continue

                if 'clear_cache' in payload:
                    self.in_memory_cache

                asyncio.create_task(self.dispatch_task(
                    client_id, chat_id, payload, user_id))

        except Exception as e:
            # Handle any exceptions that might occur
            logger.exception(e)
            await self.close_connection(
                client_id=client_id,
                chat_id=chat_id,
                code=status.WS_1011_INTERNAL_ERROR,
                reason=str(e)[:120],
            )
        finally:
            try:
                await self.close_connection(
                    client_id=client_id,
                    chat_id=chat_id,
                    code=status.WS_1000_NORMAL_CLOSURE,
                    reason='Client disconnected',
                )
            except Exception as e:
                logger.error(e)
            self.disconnect(client_id, chat_id)

    async def process_source_document(self, source_document: List[Document], chat_id, message_id,
                                      answer):
        if not source_document:
            return

        from bisheng.settings import settings
        # 使用大模型进行关键词抽取，模型配置临时方案
        keyword_conf = settings.get_default_llm() or {}
        host_base_url = keyword_conf.get('host_base_url')
        model = keyword_conf.get('model')

        if model and not host_base_url:
            db_session = next(get_session())
            model_deploy = db_session.exec(
                select(ModelDeploy).where(ModelDeploy.model == model)).first()
            if model_deploy:
                model = model if model_deploy.status == '已上线' else None
                host_base_url = model_deploy.endpoint
            else:
                logger.error('不能使用配置模型进行关键词抽取，配置不正确')

        answer_keywords = extract_answer_keys(answer, model, host_base_url)
        for doc in source_document:
            if 'bbox' in doc.metadata:
                # 表示支持溯源
                db_session = next(get_session())
                content = doc.page_content
                recall_chunk = RecallChunk(chat_id=chat_id,
                                           keywords=json.dumps(answer_keywords),
                                           chunk=content,
                                           file_id=doc.metadata.get('file_id'),
                                           meta_data=json.dumps(doc.metadata),
                                           message_id=message_id)
                db_session.add(recall_chunk)
                db_session.commit()
                db_session.refresh(recall_chunk)
