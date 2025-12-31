import json
import time
from typing import List, Any

from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.documents import Document
from langchain_core.prompts import (ChatPromptTemplate, HumanMessagePromptTemplate,
                                    SystemMessagePromptTemplate)
from langchain_core.runnables import RunnableConfig
from loguru import logger

from bisheng.chat.types import IgnoreException
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.llm.domain.services import LLMService
from bisheng.workflow.callback.event import OutputMsgData, StreamMsgOverData
from bisheng.workflow.callback.llm_callback import LLMNodeCallbackHandler
from bisheng.workflow.common.knowledge import RagUtils
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser


class RagNode(RagUtils):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 解析prompt
        self._system_prompt = PromptTemplateParser(template=self.node_params['system_prompt'])
        self._system_variables = self._system_prompt.extract()
        self._user_prompt = PromptTemplateParser(template=self.node_params['user_prompt'])
        self._user_variables = self._user_prompt.extract()

        self._qa_prompt = None

        self._llm = LLMService.get_bisheng_llm_sync(model_id=self.node_params['model_id'],
                                                    temperature=self.node_params.get('temperature', 0.3),
                                                    app_id=self.workflow_id,
                                                    app_name=self.workflow_name,
                                                    app_type=ApplicationTypeEnum.WORKFLOW,
                                                    user_id=self.user_id)
        self._minio_client = get_minio_storage_sync()

        # 是否输出结果给用户
        self._output_user = self.node_params.get('output_user', False)
        self._output_keys = [one.get("key") for one in self.node_params.get('output_user_input', [])]

        # 运行日志数据
        self._log_source_documents = {}
        self._log_system_prompt = []
        self._log_user_prompt = []
        self._log_reasoning_content = {}

        self._milvus = None
        self._es = None

    def _run(self, unique_id: str):
        ret = {}
        self.init_user_info()
        self._log_source_documents = {}
        self._log_system_prompt = []
        self._log_user_prompt = []
        self._log_reasoning_content = {}

        self.init_qa_prompt()

        self.user_questions = self.init_user_question()
        for index, question in enumerate(self.user_questions):
            output_key = self._output_keys[index]
            if question is None:
                question = ''
            question_answer = self.rag_one_question(question, output_key, unique_id)
            ret[output_key] = question_answer
        return ret

    def rag_one_question(self, question: str, output_key: str, unique_id: str) -> str:
        try:
            self.init_multi_retriever()
            self.init_rerank_model()
            source_documents = self.retrieve_question(question)
        except Exception as e:
            logger.exception(f'RagNode retrieve_question error: ')
            source_documents = [Document(page_content=str(e), metadata={})]

        qa_chain = create_stuff_documents_chain(llm=self._llm, prompt=self._qa_prompt)
        inputs = {
            "context": source_documents,
        }
        if "question" in self._qa_prompt.input_variables:
            inputs["question"] = question

        # 因为rag需要溯源所以不能用通用llm callback来返回消息。需要拿到source_document之后在返回消息内容
        llm_callback = LLMNodeCallbackHandler(callback=self.callback_manager,
                                              unique_id=unique_id,
                                              node_id=self.id,
                                              node_name=self.name,
                                              output=self._output_user,
                                              output_key=output_key,
                                              cancel_llm_end=True)
        result = qa_chain.invoke(inputs, config=RunnableConfig(callbacks=[llm_callback]))

        if self._output_user:
            self.graph_state.save_context(content=result, msg_sender='AI')
            if llm_callback.output_len == 0:
                self.callback_manager.on_output_msg(
                    OutputMsgData(node_id=self.id,
                                  name=self.name,
                                  msg=result,
                                  unique_id=unique_id,
                                  output_key=output_key,
                                  source_documents=source_documents))
            else:
                # 说明有流式输出，则触发流式结束事件, 因为需要source_document所以在此执行流式结束事件
                self.callback_manager.on_stream_over(StreamMsgOverData(
                    node_id=self.id,
                    name=self.name,
                    msg=result,
                    reasoning_content=llm_callback.reasoning_content,
                    unique_id=unique_id,
                    source_documents=source_documents,
                    output_key=output_key,
                ))

        self._log_reasoning_content[output_key] = llm_callback.reasoning_content
        self._log_source_documents[output_key] = source_documents
        return result

    def parse_log(self, unique_id: str, result: dict) -> Any:
        ret = []
        index = 0
        user_question_list = self.init_user_question()
        # 判断检索结果是否超出一定的长度, 原因是ws发送的消息超过一定的长度会报错
        source_documents = [[d.page_content for d in one] for one in self._log_source_documents.values()]
        tmp_retrieved_type = 'variable'
        tmp_retrieved_result = json.dumps(source_documents, indent=2, ensure_ascii=False)
        if len(tmp_retrieved_result.encode('utf-8')) >= 50 * 1024:  # 大于50kb的日志数据存文件
            tmp_retrieved_type = 'file'
            tmp_object_name = f'/workflow/source_document/{time.time()}.txt'
            self._minio_client.put_object_tmp_sync(tmp_object_name, tmp_retrieved_result.encode('utf-8'))
            tmp_retrieved_result = self._minio_client.get_share_link_sync(tmp_object_name,
                                                                          self._minio_client.tmp_bucket)

        for key, val in result.items():
            if tmp_retrieved_type != 'file':
                tmp_retrieved_result = json.dumps([one.page_content for one in self._log_source_documents[key]],
                                                  indent=2, ensure_ascii=False)
            one_ret = [
                {'key': f'{self.id}.user_question', 'value': user_question_list[index], "type": "variable"},
                {'key': f'{self.id}.retrieved_result', 'value': tmp_retrieved_result, "type": tmp_retrieved_type},
                {'key': 'system_prompt', 'value': self._log_system_prompt[0], "type": "params"},
                {'key': 'user_prompt', 'value': self._log_user_prompt[0], "type": "params"},
            ]
            if self._log_reasoning_content[key]:
                one_ret.append({'key': '思考内容', 'value': self._log_reasoning_content[key], "type": "params"})
            one_ret.append({'key': f'{self.id}.{key}', 'value': val, 'type': 'variable'})

            index += 1
            ret.append(one_ret)
        return ret

    def init_user_question(self) -> List[str]:
        # 默认把用户问题都转为字符串
        ret = []
        for one in self.node_params['user_question']:
            ret.append(f"{self.get_other_node_variable(one)}")
        return ret

    def init_qa_prompt(self):
        variable_map = {}
        for one in self._user_variables:
            if one == f'{self.id}.user_question':
                variable_map[one] = '$$question$$'
            elif one == f'{self.id}.retrieved_result':
                variable_map[one] = '$$context$$'
            else:
                variable_map[one] = self.get_other_node_variable(one)
        if variable_map.get(f'{self.id}.retrieved_result') is None:
            raise IgnoreException('用户提示词必须包含 retrieved_result 变量')
        user_prompt = self._user_prompt.format(variable_map)
        log_user_prompt = user_prompt.replace('$$question$$', '{user_question}').replace('$$context$$',
                                                                                         '{retrieved_result}')
        user_prompt = (user_prompt.replace('{', '{{').replace('}', '}}')
                       .replace('$$question$$', '{question}').replace('$$context$$', '{context}'))
        self._log_user_prompt.append(log_user_prompt)

        variable_map = {}
        for one in self._system_variables:
            variable_map[one] = self.get_other_node_variable(one)
        system_prompt = self._system_prompt.format(variable_map)
        system_prompt.replace('{', '{{').replace('}', '}}')
        self._log_system_prompt.append(system_prompt)

        messages_general = [
            SystemMessagePromptTemplate.from_template(system_prompt),
            HumanMessagePromptTemplate.from_template(user_prompt),
        ]
        self._qa_prompt = ChatPromptTemplate.from_messages(messages_general)
