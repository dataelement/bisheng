from typing import List

from bisheng.api.v1.schemas import LLMServerInfo


class LLMService:

    @classmethod
    def get_all_llm(cls) -> List[LLMServerInfo]:
        pass
