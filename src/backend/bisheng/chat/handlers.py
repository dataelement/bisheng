import json
from typing import Dict, List

from bisheng.api.v1.schemas import ChatMessage, ChatResponse
from bisheng.chat.manager import ChatManager
from bisheng.chat.utils import extract_answer_keys, process_graph
from bisheng.database.base import get_session
from bisheng.database.models.model_deploy import ModelDeploy
from bisheng.database.models.recall_chunk import RecallChunk
from bisheng.database.models.report import Report
from bisheng.utils.docx_temp import test_replace_string
from bisheng.utils.logger import logger
from bisheng.utils.minio_client import MinioClient
from bisheng.utils.util import get_cache_key
from bisheng_langchain.chains.autogen.auto_gen import AutoGenChain
from langchain.docstore.document import Document
from sqlmodel import select


class Handler:

    def __init__(self) -> None:
        self.handler_dict = {}
        self.handler_dict['default'] = self.process_message
        self.handler_dict['autogen'] = self.process_autogen
        self.handler_dict['auto_file'] = self.process_file
        self.handler_dict['report'] = self.process_report

    async def dispatch_task(self, session: ChatManager, client_id: str, chat_id: str, action: str,
                            payload: dict, user_id):
        with session.cache_manager.set_client_id(client_id, chat_id):
            if not action:
                action = 'default'
            if action not in self.handler_dict:
                raise Exception(f'unknown action {action}')

            await self.handler_dict[action](session, client_id, chat_id, payload, user_id)

    async def process_report(self,
                             session: ChatManager,
                             client_id: str,
                             chat_id: str,
                             payload: Dict,
                             user_id=None):
        chat_inputs = payload.pop('inputs', {})
        chat_inputs.pop('data') if 'data' in chat_inputs else {}
        chat_inputs.pop('id') if 'id' in chat_inputs else ''
        key = get_cache_key(client_id, chat_id)
        artifacts = session.in_memory_cache.get(key + '_artifacts')
        if artifacts:
            for k, value in artifacts.items():
                if k in chat_inputs:
                    chat_inputs[k] = value
        chat_message = ChatMessage(message=chat_inputs,
                                   category='question',
                                   type='bot',
                                   user_id=user_id)
        session.chat_history.add_message(client_id, chat_id, chat_message)

        # process message
        langchain_object = session.in_memory_cache.get(key)
        chat_inputs = {'inputs': chat_inputs, 'is_begin': False}
        result = await self.process_message(session, client_id, chat_id, chat_inputs, user_id)
        # judge end type
        start_resp = ChatResponse(type='start', user_id=user_id)
        await session.send_json(client_id, chat_id, start_resp)

        if langchain_object.stop_status():
            start_resp.category = 'divider'
            response = ChatResponse(message='主动退出', type='end', category='divider', user_id=user_id)
            await session.send_json(client_id, chat_id, response)

        # build report
        db_session = next(get_session())
        template = db_session.exec(
            select(Report).where(Report.flow_id == client_id).order_by(Report.id.desc())).first()
        if not template:
            logger.error('template not support')
            return
        minio_client = MinioClient()
        template_muban = minio_client.get_share_link(template.object_name)
        report_name = langchain_object.report_name
        report_name = report_name if report_name.endswith('.docx') else f'{report_name}.docx'
        test_replace_string(template_muban, result, report_name)
        file = minio_client.get_share_link(report_name)
        response = ChatResponse(type='end',
                                files=[{
                                    'file_url': file,
                                    'file_name': report_name
                                }],
                                user_id=user_id)
        await session.send_json(client_id, chat_id, response)
        close_resp = ChatResponse(type='close', category='system', user_id=user_id)
        await session.send_json(client_id, chat_id, close_resp)

    async def process_message(self,
                              session: ChatManager,
                              client_id: str,
                              chat_id: str,
                              payload: Dict,
                              user_id=None):
        # Process the graph data and chat message
        chat_inputs = payload.pop('inputs', {})
        chat_inputs.pop('id') if 'id' in chat_inputs else ''
        is_begin = payload.get('is_begin', True)
        key = get_cache_key(client_id, chat_id)

        artifacts = session.in_memory_cache.get(key + '_artifacts')
        if artifacts:
            for k, value in artifacts.items():
                if k in chat_inputs and value:
                    chat_inputs[k] = value
        chat_inputs = ChatMessage(
            message=chat_inputs,
            category='question',
            is_bot=not is_begin,
            type='bot',
            user_id=user_id,
        )
        if is_begin:
            # 从file auto trigger process_message， the question already saved
            session.chat_history.add_message(client_id, chat_id, chat_inputs)
        start_resp = ChatResponse(type='start', user_id=user_id)
        await session.send_json(client_id, chat_id, start_resp)

        # is_first_message = len(self.chat_history.get_history(client_id=client_id)) <= 1
        # Generate result and thought
        try:
            logger.debug(f'Generating result and thought key={key}')
            langchain_object = session.in_memory_cache.get(key)
            result, intermediate_steps, source_doucment = await process_graph(
                langchain_object=langchain_object,
                chat_inputs=chat_inputs,
                websocket=session.active_connections[get_cache_key(client_id, chat_id)],
            )
        except Exception as e:
            # Log stack trace
            logger.exception(e)
            end_resp = ChatResponse(type='end',
                                    intermediate_steps=f'分析出错，{str(e)}',
                                    user_id=user_id)
            await session.send_json(client_id, chat_id, end_resp)
            close_resp = ChatResponse(type='close', user_id=user_id)
            if not chat_id:
                # 技能编排页面， 无法展示intermediate
                await session.send_json(client_id, chat_id, start_resp)
                end_resp.message = end_resp.intermediate_steps
                end_resp.intermediate_steps = None
                await session.send_json(client_id, chat_id, end_resp)
            await session.send_json(client_id, chat_id, close_resp)
            return

        # Send a response back to the frontend, if needed
        intermediate_steps = intermediate_steps or ''
        # history = self.chat_history.get_history(client_id, chat_id, filter_messages=False)
        await self.intermediate_logs(session, client_id, chat_id, user_id, intermediate_steps)
        source = 0
        extra = {}
        if isinstance(result, Document):
            # 返回的是Document
            metadata = result.metadata
            question = result.page_content
            result = eval(metadata.get('extra', '{}')).get('answer')
            source = 4
            extra = {'qa': f'本答案来源于已有问答库: {question}'}
        elif source_doucment and chat_id:
            if any(not doc.metadata.get('right', True) for doc in source_doucment):
                source = 2
            elif all(
                    doc.metadata.get('extra') and eval(doc.metadata.get('extra')).get('url')
                    for doc in source_doucment):
                source = 3
                doc = [{
                    'title': doc.metadata.get('source'),
                    'url': eval(doc.metadata.get('extra', '{}')).get('url')
                } for doc in source_doucment]
                extra = {'doc': [dict(s) for s in set(frozenset(d.items()) for d in doc)]}
            else:
                source = 1

        if source:
            for doc in source_doucment:
                # 确保每个chunk 都可溯源
                if 'bbox' not in doc.metadata or not doc.metadata['bbox']:
                    source = False
        # 最终结果
        if isinstance(langchain_object, AutoGenChain):
            # 群聊，最后一条消息重复，不进行返回
            start_resp.category = 'divider'
            await session.send_json(client_id, chat_id, start_resp)
            response = ChatResponse(message='本轮结束', type='end', category='divider', user_id=user_id)
            await session.send_json(client_id, chat_id, response)
        else:
            # 正常
            if is_begin:
                start_resp.category = 'answer'
                await session.send_json(client_id, chat_id, start_resp)
                response = ChatResponse(message=result,
                                        extra=json.dumps(extra),
                                        type='end',
                                        category='answer',
                                        user_id=user_id,
                                        source=int(source))
                await session.send_json(client_id, chat_id, response)

        # 循环结束
        if is_begin:
            close_resp = ChatResponse(type='close', user_id=user_id)
            await session.send_json(client_id, chat_id, close_resp)

        if source:
            # 处理召回的chunk
            await self.process_source_document(
                source_doucment,
                chat_id,
                response.message_id,
                result,
            )
        return result

    async def process_file(self, session: ChatManager, client_id: str, chat_id: str, payload: dict,
                           user_id: int):
        file_name = payload['inputs']['data'][0]['value']
        batch_question = payload['inputs']['questions']
        # 如果L3
        file = ChatMessage(is_bot=False,
                           files=[{
                               'file_name': file_name
                           }],
                           type='end',
                           user_id=user_id)
        session.chat_history.add_message(client_id, chat_id, file)
        start_resp = ChatResponse(type='start', category='system', user_id=user_id)

        key = get_cache_key(client_id, chat_id)
        langchain_object = session.in_memory_cache.get(key)
        input_key = langchain_object.input_keys[0]

        report = ''
        logger.info(f'process_file batch_question={batch_question}')
        for question in batch_question:
            if not question:
                continue
            payload = {'inputs': {input_key: question}, 'is_begin': False}
            start_resp.category == 'question'
            await session.send_json(client_id, chat_id, start_resp)
            step_resp = ChatResponse(type='end',
                                     intermediate_steps=question,
                                     category='question',
                                     user_id=user_id)
            await session.send_json(client_id, chat_id, step_resp)
            result = await self.process_message(session, client_id, chat_id, payload, user_id)
            response_step = ChatResponse(intermediate_steps=result,
                                         type='start',
                                         category='answer',
                                         user_id=user_id)
            await session.send_json(client_id, chat_id, response_step)
            response_step.type = 'end'
            await session.send_json(client_id, chat_id, response_step)
            report = f"""{report}### {question} \n {result} \n """

        start_resp.category = 'report'
        await session.send_json(client_id, chat_id, start_resp)
        response = ChatResponse(type='end',
                                intermediate_steps=report,
                                category='report',
                                user_id=user_id)
        await session.send_json(client_id, chat_id, response)
        close_resp = ChatResponse(type='close', category='system', user_id=user_id)
        await session.send_json(client_id, chat_id, close_resp)

    async def process_autogen(self, session: ChatManager, client_id: str, chat_id: str,
                              payload: dict, user_id: int):
        key = get_cache_key(client_id, chat_id)
        langchain_object = session.in_memory_cache.get(key)
        logger.info(f'reciever_human_interactive langchain={langchain_object}')
        action = payload.get('action')
        if action.lower() == 'stop':
            if hasattr(langchain_object, 'stop'):
                logger.info('reciever_human_interactive langchain_objct')
                await langchain_object.stop()
            else:
                logger.error(f'act=auto_gen act={action}')
        elif action.lower() == 'continue':
            # autgen_user 对话的时候，进程 wait() 需要换新
            if hasattr(langchain_object, 'input'):
                await langchain_object.input(payload.get('inputs'))
                # 新的对话开始，
                start_resp = ChatResponse(type='start')
                await session.send_json(client_id, chat_id, start_resp)
            else:
                logger.error(f'act=auto_gen act={action}')

    async def intermediate_logs(self, session: ChatManager, client_id, chat_id, user_id,
                                intermediate_steps):
        end_resp = ChatResponse(type='end', user_id=user_id)
        if not intermediate_steps:
            return await session.send_json(client_id, chat_id, end_resp, add=False)

        # 将最终的分析过程存数据库
        steps = []
        if isinstance(intermediate_steps, list):
            # autogen produce multi dialog
            for message in intermediate_steps:
                content = message.get('message')
                log = message.get('log', '')
                sender = message.get('sender')
                receiver = message.get('receiver')
                is_bot = False if receiver and receiver.get('is_bot') else True
                category = message.get('category', 'processing')
                msg = ChatResponse(message=content,
                                   intermediate_steps=log,
                                   sender=sender,
                                   receiver=receiver,
                                   type='end',
                                   user_id=user_id,
                                   is_bot=is_bot,
                                   category=category)
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
        await session.send_json(client_id, chat_id, end_resp, add=False)

        for step in steps:
            # save chate message
            session.chat_history.add_message(client_id, chat_id, step)

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
