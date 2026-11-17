"""昆联平台大模型节点：通过 OIDC Token Exchange 调用昆联 Chat Completions。"""

from typing import Any

from loguru import logger
from pydantic import ValidationError

from bisheng.common.errcode.flow import PlatformLLMConfigurationError
from bisheng.utils.async_utils import run_async_safe
from bisheng.workflow.application import platform_llm
from bisheng.workflow.callback.event import OutputMsgData
from bisheng.workflow.domain.schemas.platform_llm import PlatformModelReference
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser


class PlatformLLMNode(BaseNode):
    """沿用单次文本对话配置，调用昆联平台授权大模型的固定版本推理接口。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._output_user = bool(self.node_params.get("output_user", True))
        raw_temp = self.node_params.get("temperature", 1.0)
        self._temperature = 1.0 if raw_temp is None else float(raw_temp)
        self._model_ref = self.node_params.get("model_ref")

        self._system_prompt = PromptTemplateParser(template=self.node_params.get("system_prompt") or "")
        self._system_variables = self._system_prompt.extract()
        self._user_prompt = PromptTemplateParser(template=self.node_params.get("user_prompt") or "")
        self._user_variables = self._user_prompt.extract()

        self._rendered_system_prompt = ""
        self._rendered_user_prompt = ""
        self._reasoning_content = ""
        self._resolved_ref: PlatformModelReference | None = None

    def _format_prompt(self, parser: PromptTemplateParser, variables: list[str]) -> str:
        variable_map = {one: self.get_other_node_variable(one) for one in variables}
        return parser.format(variable_map)

    def _run(self, unique_id: str) -> dict[str, Any]:
        try:
            ref = PlatformModelReference.model_validate(self._model_ref)
        except ValidationError:
            raise PlatformLLMConfigurationError() from None
        self._resolved_ref = ref

        system = self._format_prompt(self._system_prompt, self._system_variables)
        user = self._format_prompt(self._user_prompt, self._user_variables)
        self._rendered_system_prompt = system
        self._rendered_user_prompt = user

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        logger.debug(
            "platform_llm invoke node_id={} resource_id={} version_id={} call_id={}",
            self.id,
            ref.resource_id,
            ref.version_id,
            ref.call_id,
        )
        completion = run_async_safe(
            platform_llm.get_service().invoke_chat(
                int(self.user_id),
                call_id=ref.call_id,
                messages=messages,
                temperature=self._temperature,
            ),
            timeout=None,
        )
        self._reasoning_content = completion.reasoning_content
        if self._output_user and completion.content:
            self.callback_manager.on_output_msg(
                OutputMsgData(
                    node_id=self.id,
                    name=self.name,
                    msg=completion.content,
                    unique_id=unique_id,
                    output_key="output",
                )
            )
            if self.graph_state.history_memory is not None:
                self.graph_state.save_context(content=completion.content, msg_sender="AI")
        return {"output": completion.content}

    def parse_log(self, unique_id: str, result: dict) -> Any:
        entries: list[dict[str, Any]] = [
            {"key": "system_prompt", "value": self._rendered_system_prompt, "type": "params"},
            {"key": "user_prompt", "value": self._rendered_user_prompt, "type": "params"},
        ]
        if self._resolved_ref is not None:
            entries.append({"key": "model_ref", "value": self._resolved_ref.model_dump(), "type": "params"})
        if self._reasoning_content:
            entries.append({"key": "Thinking about content", "value": self._reasoning_content, "type": "params"})
        for key, value in result.items():
            entries.append({"key": f"{self.id}.{key}", "value": value, "type": "variable"})
        return [entries]
