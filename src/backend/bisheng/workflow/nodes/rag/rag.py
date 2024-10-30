from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser


class RagNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 判断是知识库还是临时文件列表
        self._knowledge_type = self.node_params["knowledge_id"]["type"]
        self._knowledge_value = [one["key"] for one in self.node_params["knowledge_id"]["value"]]

        self._knowledge_auth = self.node_params["user_auth"]
        self._max_chunk_size = self.node_params["max_chunk_size"]

        self._system_prompt = PromptTemplateParser(template=self.node_params["system_prompt"])
        self._user_prompt = PromptTemplateParser(template=self.node_params["user_prompt"])

        self.llm = LLMService.get_bisheng_llm(model_id=self.node_params["model_id"],
                                              temperature=self.node_params.get("temperature", 0.3))


    def _run(self):
        pass
