from bisheng.settings import settings


class AssistantUtils:

    @classmethod
    def get_gpts_conf(cls, key=None):
        gpts_conf = settings.get_from_db('gpts')
        if key:
            return gpts_conf.get(key)
        return gpts_conf

    @classmethod
    def get_llm_conf(cls, llm_name: str) -> dict:
        llm_list = cls.get_gpts_conf('llms')
        for one in llm_list:
            if one['model_name'] == llm_name:
                return one
        return llm_list[0]

    @classmethod
    def get_prompt_type(cls):
        return cls.get_gpts_conf('prompt_type')

    @classmethod
    def get_agent_executor(cls):
        return cls.get_gpts_conf('agent_executor')
