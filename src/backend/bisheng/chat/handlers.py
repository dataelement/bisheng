import json
import time
from queue import Queue
from typing import Dict

from bisheng.api.utils import build_input_keys_response
from bisheng.api.v1.schemas import ChatMessage, ChatResponse
from bisheng.chat.manager import ChatManager
from bisheng.chat.utils import judge_source, process_graph, process_source_document
from bisheng.database.base import session_getter
from bisheng.database.models.report import Report
from bisheng.interface.importing.utils import import_by_type
from bisheng.interface.initialize.loading import instantiate_llm
from bisheng.settings import settings
from bisheng.utils.docx_temp import test_replace_string
from bisheng.utils.logger import logger
from bisheng.utils.minio_client import MinioClient
from bisheng.utils.threadpool import thread_pool
from bisheng.utils.util import get_cache_key
from bisheng_langchain.chains.autogen.auto_gen import AutoGenChain
from langchain.chains.llm import LLMChain
from langchain_core.prompts.prompt import PromptTemplate
from sqlmodel import select


class Handler:

    def __init__(self, stream_queue: Queue) -> None:
        self.handler_dict = {
            'default': self.process_message,
            'autogen': self.process_autogen,
            'auto_file': self.process_file,
            'report': self.process_report,
            'stop': self.process_stop
        }
        # 记录流式输出的内容
        self.stream_queue = stream_queue

    async def dispatch_task(self, session: ChatManager, client_id: str, chat_id: str, action: str,
                            payload: dict, user_id):
        logger.info(f'dispatch_task payload={payload.get("inputs")}')
        start_time = time.time()
        with session.cache_manager.set_client_id(client_id, chat_id):
            if not action:
                action = 'default'
            if action not in self.handler_dict:
                raise Exception(f'unknown action {action}')
            if action != 'stop':
                # 清空流式输出队列，防止上次的回答污染本次回答
                while not self.stream_queue.empty():
                    self.stream_queue.get()

            await self.handler_dict[action](session, client_id, chat_id, payload, user_id)
            logger.info(f'dispatch_task done timecost={time.time() - start_time}')
        return client_id, chat_id

    async def process_stop(self, session: ChatManager, client_id: str, chat_id: str, payload: Dict,
                           user_id):
        key = get_cache_key(client_id, chat_id)
        langchain_object = session.in_memory_cache.get(key)
        action = payload.get('action')
        if isinstance(langchain_object, AutoGenChain):
            if hasattr(langchain_object, 'stop'):
                logger.info('reciever_human_interactive langchain_objct')
                await langchain_object.stop()
            else:
                logger.error(f'act=auto_gen act={action}')
        else:
            # 普通技能的stop
            res = thread_pool.cancel_task([key])  # 将进行中的任务进行cancel
            if res[0]:
                # message = payload.get('inputs') or '手动停止'
                res = ChatResponse(type='end', user_id=user_id, message='')
                close = ChatResponse(type='close')
                await session.send_json(client_id, chat_id, res, add=False)
                await session.send_json(client_id, chat_id, close, add=False)
        answer = ''
        # 记录中止后产生的流式输出内容
        while not self.stream_queue.empty():
            answer += self.stream_queue.get()
        if answer.strip():
            chat_message = ChatMessage(message=answer,
                                       category='answer',
                                       type='end',
                                       user_id=user_id,
                                       remark='break_answer',
                                       is_bot=True)
            session.chat_history.add_message(client_id, chat_id, chat_message)
        logger.info('process_stop done')

    async def process_report(self,
                             session: ChatManager,
                             client_id: str,
                             chat_id: str,
                             payload: Dict,
                             user_id=None):
        chat_inputs = payload.pop('inputs', {})
        chat_inputs.pop('data', '')
        chat_inputs.pop('id', '')
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
            response = ChatResponse(message='主动退出',
                                    type='end',
                                    category='divider',
                                    user_id=user_id)
            await session.send_json(client_id, chat_id, response)

        # build report
        with session_getter() as db_session:
            template = db_session.exec(
                select(Report).where(Report.flow_id == client_id).order_by(
                    Report.id.desc())).first()
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

    def recommend_question(self, langchain_obj, chat_history: list):
        prompt = """给定以下历史聊天消息:
        {history}

        总结提炼用户可能接下来会提问的3个问题，请直接输出问题，使用换行符分割问题，不要添加任何修饰文字或前后缀。
        """
        if hasattr(langchain_obj, 'llm'):
            llm_chain = LLMChain(llm=langchain_obj.llm,
                                 prompt=PromptTemplate.from_template(prompt))
        else:
            keyword_conf = settings.get_default_llm() or {}
            if keyword_conf:
                node_type = keyword_conf.pop('type', 'HostQwenChat')  # 兼容旧配置
                class_object = import_by_type(_type='llms', name=node_type)
                llm = instantiate_llm(node_type, class_object, keyword_conf)

                llm_chain = LLMChain(llm=llm, prompt=PromptTemplate.from_template(prompt))
        if llm_chain:
            questions = llm_chain.predict(history=chat_history)
            return questions.split('\n')
        else:
            logger.info('llm_chain is None recommend_over')
            return []

    async def process_message(self,
                              session: ChatManager,
                              client_id: str,
                              chat_id: str,
                              payload: Dict,
                              user_id=None):
        # Process the graph data and chat message
        chat_inputs = payload.pop('inputs', {})
        chat_inputs.pop('id', '')
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
                flow_id=client_id,
                chat_id=chat_id,
                stream_queue=self.stream_queue,
            )

            # questions = []
            # if is_begin and langchain_object.memory and langchain_object.memory.buffer:
            #     questions = self.recommend_question(langchain_object,
            #                                         langchain_object.memory.buffer)

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
        extra = {}
        source, result = await judge_source(result, source_doucment, chat_id, extra)

        # 最终结果
        if isinstance(langchain_object, AutoGenChain):
            # 群聊，最后一条消息重复，不进行返回
            start_resp.category = 'divider'
            await session.send_json(client_id, chat_id, start_resp)
            response = ChatResponse(message='本轮结束',
                                    type='end',
                                    category='divider',
                                    user_id=user_id)
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
            await process_source_document(
                source_doucment,
                chat_id,
                response.message_id,
                result,
            )

        return result

    async def process_file(self, session: ChatManager, client_id: str, chat_id: str, payload: dict,
                           user_id: int):
        file_name = payload['inputs']
        batch_question = payload['inputs']['questions']
        # 如果L3
        file = ChatMessage(is_bot=False, message=file_name, type='end', user_id=user_id)
        session.chat_history.add_message(client_id, chat_id, file)
        start_resp = ChatResponse(type='start', category='system', user_id=user_id)

        key = get_cache_key(client_id, chat_id)
        langchain_object = session.in_memory_cache.get(key)
        if batch_question and len(langchain_object.input_keys) == 0:
            # prompt 没有可以输入问题的地方
            await session.send_json(client_id, chat_id, start_resp)
            log_resp = start_resp.copy()
            log_resp.intermediate_steps = '当前Prompt设置无用户输入，PresetQuestion 不生效'
            log_resp.type = 'end'
            await session.send_json(client_id, chat_id, log_resp)
            input_key = 'input'
            input_dict = {}
        else:
            input_key = list(build_input_keys_response(langchain_object,
                                                       {})['input_keys'].keys())[0]
            input_dict = {k: '' for k in langchain_object.input_keys}

        batch_question = ['start'] if not batch_question else batch_question  # 确保点击确定，会执行LLM
        report = ''
        logger.info(f'process_file batch_question={batch_question} input_key={input_key}')
        for question in batch_question:
            if not question:
                continue
            input_dict[input_key] = question
            payload = {'inputs': input_dict, 'is_begin': False}
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
            response_step.type = 'end'
            await session.send_json(client_id, chat_id, response_step)
            report = f"""{report}### {question} \n {result} \n """

        if len(batch_question) > 1:
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
        if action.lower() == 'continue':
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
                # autogen produce message object
                if isinstance(message, str):
                    log = message
                    is_bot = True
                    category = 'processing'
                    content = sender = receiver = None
                else:
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
            from langchain.schema import Document  # noqa
            if chat_id and intermediate_steps.strip():
                finally_log = ''
                for s in intermediate_steps.split('\n'):
                    # 清理召回日志中的一些冗余日志
                    if 'source_documents' in s:
                        answer = eval(s.split(':', 1)[1])
                        if 'result' in answer:
                            finally_log += 'Answer: ' + answer.get('result') + '\n\n'
                    else:
                        finally_log += s + '\n\n'
                msg = ChatResponse(intermediate_steps=finally_log, type='end', user_id=user_id)
                steps.append(msg)
            else:
                # 只有L3用户给出详细的log
                end_resp.intermediate_steps = intermediate_steps
        await session.send_json(client_id, chat_id, end_resp, add=False)

        for step in steps:
            # save chate message
            session.chat_history.add_message(client_id, chat_id, step)
