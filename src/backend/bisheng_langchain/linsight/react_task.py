import asyncio
import json
from datetime import datetime

from langchain_core.messages import ToolMessage, AIMessage, HumanMessage, BaseMessage

from bisheng_langchain.linsight.const import TaskStatus, CallUserInputToolName
from bisheng_langchain.linsight.event import NeedUserInput, ExecStep
from bisheng_langchain.linsight.react_prompt import ReactSingleAgentPrompt, ReactLoopAgentPrompt
from bisheng_langchain.linsight.task import BaseTask
from bisheng_langchain.linsight.utils import encode_str_tokens, generate_uuid_str, \
    extract_json_from_markdown


class ReactTask(BaseTask):

    async def get_history_str(self) -> str:
        """Get the history string for the history."""
        history_str = ""
        tool_messages = []
        remain_messages = []
        all_tool_messages = []
        i = 0
        while i < len(self.history):
            message = self.history[i]
            if isinstance(message, AIMessage) and "tool_calls" in message.additional_kwargs:
                if i + 1 < len(self.history):
                    one = self.history[i + 1]
                    if (isinstance(one, ToolMessage) and
                            one.tool_call_id == message.additional_kwargs["tool_calls"][0]["id"]):
                        message = json.loads(message.content)
                        message["观察"] = one.content
                        message["结束"] = one.additional_kwargs.get("is_end", False)
                        all_tool_messages.append(message)
                        history_str += "\n" + json.dumps(message, ensure_ascii=False, indent=2)
                        i += 1
                    else:
                        raise Exception("AIMessage with tool_calls should be followed by ToolMessage")
            elif isinstance(message, ToolMessage):
                raise Exception("ToolMessage should be after AIMessage with tool_calls")
            else:
                history_str += "\n" + message.content
                remain_messages.append(message)
            i += 1

        all_tool_messages_str = json.dumps(all_tool_messages, ensure_ascii=False, indent=2)
        if len(encode_str_tokens(all_tool_messages_str)) > self.exec_config.tool_buffer:
            messages_str = ''
            for one in self.history:
                messages_str += "\n" + one.content + ","
            messages_str = messages_str.rstrip(",")
            messages_str = f"[{messages_str}\n]"

            history_summary = await self.summarize_history(messages_str)
            # 将总结后的历史记录插入到system_message后面
            remain_messages.append(HumanMessage(content=history_summary))
            self.all_history.append(self.history)
            self.history = remain_messages
            return "\n".join([one.content for one in remain_messages])

        return history_str

    async def build_messages_with_history(self) -> list[BaseMessage]:
        """Build messages with history for the React task."""
        # It should return a prompt that will be used in the React task.
        current_time = datetime.now().strftime("%Y-%m-%d %H")
        tools_json = self.task_manager.get_all_tool_schema_str
        history_str = await self.get_history_str()

        if self.node_loop and self.parent_id:
            prompt = ReactLoopAgentPrompt.format(profile=self.profile,
                                                 current_time=current_time,
                                                 file_dir=self.file_dir,
                                                 tools_json=tools_json,
                                                 original_query=self.original_query,
                                                 original_method=self.original_method,
                                                 original_done=self.original_done,
                                                 last_answer=await self.get_input_str(),
                                                 single_sop=self.sop,
                                                 step_id=self.step_id,
                                                 target=self.target,
                                                 history=history_str,
                                                 file_list_str=self.file_list_str)
        else:
            prompt = ReactSingleAgentPrompt.format(profile=self.profile,
                                                   current_time=current_time,
                                                   file_dir=self.file_dir,
                                                   tools_json=tools_json,
                                                   sop=self.finally_sop,
                                                   query=self.query,
                                                   step_list=self.task_manager.get_step_list(),
                                                   processed_steps=self.task_manager.get_processed_steps(),
                                                   input_str=await self.get_input_str(),
                                                   step_id=self.step_id,
                                                   target=self.target,
                                                   single_sop=self.sop,
                                                   history=history_str,
                                                   file_list_str=self.file_list_str)
        return [HumanMessage(content=prompt)]

    async def parse_react_result(self, content: str) -> (BaseMessage, bool):
        response_json = extract_json_from_markdown(content)
        step_type = response_json.get("类型", "未知")
        thinking = response_json.get("思考", "未提供思考过程")
        action = response_json.get("行动", "")
        params = response_json.get("参数", {})
        observation = response_json.get("观察", "")
        generate_content = response_json.get("生成内容", "")
        is_end = response_json.get("结束", False)
        if isinstance(is_end, str):
            is_end = is_end.lower() == "true"
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except json.decoder.JSONDecodeError:
                params = {}

        # 说明是工具执行, 执行工具

        if action and action == "回答":
            self.answer.append(str(generate_content))

        if step_type == "固定步骤":
            result_dict = {
                "思考": thinking,
                "结束": "True" if is_end else "False",
                "类型": step_type,
                "行动": action,
                "参数": params,
                "生成内容": generate_content,
            }
            await self.put_event(ExecStep(task_id=self.id,
                                          call_id=generate_uuid_str(),
                                          call_reason=response_json.get("调用原因", ""),
                                          name=action,
                                          params=params,
                                          output=str(generate_content),
                                          step_type='react_step',
                                          status="end"))
            message = AIMessage(content=json.dumps(result_dict, ensure_ascii=False, indent=2))
        else:
            result_dict = {
                "思考": thinking,
                "结束": "True" if is_end else "False",
                "类型": "工具",
                "行动": action,
                "参数": params,
                "观察": observation,
            }
            message = AIMessage(content=json.dumps(result_dict, ensure_ascii=False, indent=2), additional_kwargs={
                "tool_calls": [
                    {"id": generate_uuid_str(), "name": action, "args": params}
                ]
            })
        message.additional_kwargs["is_end"] = is_end
        return message, is_end

    async def execute_react_tool(self, message: AIMessage) -> (str, bool):
        """Execute the tool based on the AIMessage."""
        if "tool_calls" not in message.additional_kwargs:
            raise Exception("AIMessage does not contain tool_calls")
        tool_calls = message.additional_kwargs["tool_calls"]
        if not tool_calls or not isinstance(tool_calls, list):
            raise Exception("tool_calls is empty or not a list")
        tool_call = tool_calls[0]
        action = tool_call.get("name", "")
        params = tool_call.get("args", {})
        call_id = tool_call.get("id", "")
        if not action:
            raise Exception("tool call name is empty")

        is_end = message.additional_kwargs.get("is_end", False)
        _call_reason = params.get("call_reason", "")
        # 等待用户输入的特殊工具调用
        if action == CallUserInputToolName:
            # 等待用户输入
            self.status = TaskStatus.INPUT.value
            await self.put_event(NeedUserInput(task_id=self.id, call_reason=_call_reason))
            # 等待用户输入
            while self.status != TaskStatus.INPUT_OVER.value:
                await asyncio.sleep(0.5)

            # 用户输入结束继续执行
            self.status = TaskStatus.PROCESSING.value
            observation = self.user_input
            self.user_input = None
        else:
            # 正常工具调用
            await self.put_event(ExecStep(task_id=self.id,
                                          call_id=call_id,
                                          call_reason=_call_reason,
                                          name=action,
                                          params=params,
                                          status="start"))
            observation, flag = await self._base_ainvoke_tool(action, params)
            # 说明工具调用失败
            if not flag:
                is_end = False
            await self.put_event(ExecStep(task_id=self.id,
                                          call_id=call_id,
                                          call_reason=_call_reason,
                                          name=action,
                                          params=params,
                                          output=observation,
                                          status="end"))
        message = ToolMessage(content=observation, tool_call_id=call_id, additional_kwargs={"is_end": is_end})
        return message, is_end

    async def _ainvoke(self) -> None:
        self.status = TaskStatus.PROCESSING.value
        if self.node_loop and not self.parent_id:
            return await self.ainvoke_loop()

        is_end = False
        # json解析失败重试三次
        json_decode_error = 0
        step_index = 0
        while step_index < self.exec_config.max_steps:
            # 根据历史消息判断需要 执行工具、调用模型
            latest_message = self.history[-1] if self.history else None
            if latest_message and isinstance(latest_message, AIMessage):
                if "tool_calls" in latest_message.additional_kwargs:
                    # 说明需要调用工具
                    new_message, is_end = await self.execute_react_tool(latest_message)
                    self.history.append(new_message)
                    # 执行工具不消耗执行步数
                    step_index -= 1
                    continue
            is_end = self.history[-1].additional_kwargs.get("is_end", False) if self.history else False
            if is_end:
                break

            messages = await self.build_messages_with_history()
            if json_decode_error > 0:
                res = await self._ainvoke_llm_without_tools(messages, temperature=self.exec_config.retry_temperature)
            else:
                res = await self._ainvoke_llm_without_tools(messages)

            try:
                message, is_end = await self.parse_react_result(res.content)
            except Exception as e:
                if json_decode_error >= self.exec_config.retry_num:
                    raise e
                json_decode_error += 1
                continue
            self.exec_config.prompt_manage.insert_prompt("\n".join([one.text() for one in messages]), "task_exec", {
                "task_id": self.id,
                "all_history_index": len(self.all_history),
                "history_index": len(self.history),
            })
            self.history.append(message)
            step_index += 1

        if is_end:
            self.status = TaskStatus.SUCCESS.value
        else:
            self.status = TaskStatus.FAILED.value
            self.answer.append("task exec over max steps and not generate answer")
        return None

    async def generate_sub_tasks(self, sub_tasks_info: list[dict] = None) -> list['ReactTask']:
        if sub_tasks_info is None:
            sub_tasks_info = await self._get_sub_tasks()
        return [ReactTask(**one) for one in sub_tasks_info]
