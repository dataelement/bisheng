from typing import Any, Dict, List
import json
from loguru import logger

from bisheng.api.services.llm import LLMService
from bisheng.workflow.callback.event import GuideQuestionData
from bisheng.workflow.callback.llm_callback import LLMNodeCallbackHandler
from bisheng.workflow.nodes.base import BaseNode
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig


class QuestionPredictNode(BaseNode):
    """
    基于消息历史预测用户下一个问题的节点
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._output_user = False
        # 预测问题数量
        self._predict_count = self.node_params.get("predict_count")
        if self._predict_count is None:
            self._predict_count = 3
        else:
            self._predict_count = self._predict_count.get("value", 3)

        # 历史消息数量限制
        self._history_limit = self.node_params.get("history_limit")
        if self._history_limit is None:
            self._history_limit = 10
        else:
            self._history_limit = self._history_limit.get("value", 10)

        # 自定义系统提示词
        self._custom_system_prompt = self.node_params.get("custom_system_prompt", "")

        # 存储日志所需数据
        self._system_prompt_used = ""
        self._history_used = []

        # 初始化llm对象
        self._llm = LLMService.get_bisheng_llm(
            model_id=self.node_params["model_id"], temperature=self.node_params.get("temperature", 0.7), cache=False
        )

    def _build_system_prompt(self) -> str:
        """构建系统提示词"""
        if self._custom_system_prompt:
            base_prompt = self._custom_system_prompt
        else:
            base_prompt = """你是一个智能助手，专门负责分析用户的对话历史，预测用户可能会问的下一个问题。

请基于以下对话历史，分析用户的意图、兴趣点和对话发展趋势，预测用户最可能问的{predict_count}个问题。

分析要点：
1. 用户的关注焦点和兴趣方向
2. 对话的逻辑发展趋势
3. 用户可能的深入需求
4. 相关的延伸话题

请确保预测的问题：
- 与对话上下文相关
- 符合用户的交流风格
- 具有实际价值和可操作性
- 按照可能性从高到低排序"""

        return base_prompt.format(predict_count=self._predict_count)

    def _build_output_format_prompt(self) -> str:
        """构建输出格式说明"""
        return """
请以JSON格式返回结果：
{
    "predicted_questions": [
        {
            "question": "预测的问题内容",
            "probability": "可能性评分(0-1)",
            "reason": "预测理由"
        }
    ],
    "analysis": "对话趋势分析总结"
}

确保返回有效的JSON格式。"""    

    def _get_chat_history(self) -> List[Dict]:
        """获取聊天历史"""
        try:
            # 从图状态获取历史消息
            history_list = self.graph_state.get_history_list(self._history_limit)

            # 转换为更易处理的格式
            formatted_history = []
            for msg in history_list:
                if hasattr(msg, "content"):
                    content = msg.content
                    if isinstance(content, list) and len(content) > 0:
                        # 处理多模态消息，只取文本部分
                        text_content = ""
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                text_content += item.get("text", "")
                        content = text_content

                    role = "user" if hasattr(msg, "__class__") and "Human" in msg.__class__.__name__ else "assistant"
                    formatted_history.append({"role": role, "content": str(content)})

            return formatted_history
        except Exception as e:
            logger.warning(f"获取聊天历史失败: {e}")
            return []

    def _format_history_for_prompt(self, history: List[Dict]) -> str:
        """将历史消息格式化为提示词"""
        if not history:
            return "暂无对话历史"

        formatted = "对话历史：\n"
        for i, msg in enumerate(history, 1):
            role_name = "用户" if msg["role"] == "user" else "助手"
            formatted += f"{i}. {role_name}: {msg['content']}\n"

        return formatted

    def _parse_llm_output(self, output: str) -> Dict:
        """解析LLM输出"""
        try:
            # 尝试解析JSON
            # 清理可能的markdown代码块标记
            cleaned_output = output.strip()
            if cleaned_output.startswith("```json"):
                cleaned_output = cleaned_output[7:]
            if cleaned_output.endswith("```"):
                cleaned_output = cleaned_output[:-3]
            cleaned_output = cleaned_output.strip()

            result = json.loads(cleaned_output)
            return {
                "questions": result.get("predicted_questions", []),
                "analysis": result.get("analysis", ""),
            }
            
        except Exception as e:
            logger.error(f"解析LLM输出失败: {e}")
            return {
                "questions": [{"question": "解析预测结果失败", "probability": 0.0, "reason": str(e)}],
                "analysis": "输出解析出错",
                "format": "error",
                "raw_output": output,
            }

    def _run(self, unique_id: str) -> Dict[str, Any]:
        """执行节点逻辑"""
        # 获取聊天历史
        chat_history = self._get_chat_history()
        self._history_used = chat_history

        # 构建提示词
        system_prompt = self._build_system_prompt()
        self._system_prompt_used = system_prompt

        history_text = self._format_history_for_prompt(chat_history)
        output_format = self._build_output_format_prompt()

        user_prompt = f"{history_text}\n\n{output_format}"

        # 设置回调
        llm_callback = LLMNodeCallbackHandler(
            callback=self.callback_manager,
            unique_id=unique_id,
            node_id=self.id,
            output=self._output_user,
            output_key="predicted_questions",
        )
        config = RunnableConfig(callbacks=[llm_callback])

        # 构建消息
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]

        # 调用LLM
        result = self._llm.invoke(messages, config=config)

        # 解析结果
        parsed_result = self._parse_llm_output(result.content)

        # 准备返回结果
        output_data = {
            "predicted_questions": parsed_result["questions"],
            "analysis": parsed_result["analysis"],
        }

        self.callback_manager.on_guide_question(
            GuideQuestionData(
                node_id=self.id,
                guide_question=[q["question"] for q in parsed_result["questions"]],
                unique_id=unique_id,
            )
        )


        logger.debug(f"QuestionPredict result: {output_data}")
        return output_data

    def parse_log(self, unique_id: str, result: dict) -> Any:
        """解析日志"""
        log_data = []

        for key, value in result.items():
            log_data.append({"key": f"{self.id}.{key}", "value": value, "type": "variable"})

        return [log_data]
