from typing import Dict

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

    @classmethod
    def get_default_retrieval(cls) -> str:
        return cls.get_gpts_conf('default-retrieval')

    @classmethod
    def get_initdb_conf_by_more_key(cls, key: str) -> Dict:
        """
        根据多层级的key，获取对应的配置。
        :param key: 例如：gpts.tools.code_interpreter  表示获取 gpts['tools']['code_interpreter']的内容
        """
        # 因为属于系统配置级别，不做不存在的判断。不存在直接抛出异常
        key_list = key.split('.')
        root_conf = settings.get_from_db(key_list[0].strip())
        for one in key_list[1:]:
            root_conf = root_conf[one.strip()]
        return root_conf
