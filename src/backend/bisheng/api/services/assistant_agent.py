from bisheng.database.models.assistant import Assistant, AssistantLinkDao
from bisheng.settings import settings


class AssistantAgent:
    def __init__(self, assistant_info: Assistant, chat_id: str):
        self.assistant_info = assistant_info
        self.chat_id = chat_id
        self.tools = []
        self.agent = None
        self.debug = True
        if self.chat_id:
            self.debug = False

        self.convert_link_to_tool()
        self.init_agent()

    def convert_link_to_tool(self):
        """
        初始化工具、技能、知识库等信息
        """
        # todo zgq: 对接姚老师的link转tool接口
        links = AssistantLinkDao.get_assistant_link(self.assistant_info.id)
        print(links)
        pass

    def init_agent(self):
        """
        初始化智能体的agent
        """
        # todo zgq: 对接算法组的agent初始化接口
        self.agent = 1

    def run(self, input_msg: str):
        """
        运行智能体对话
        """

    @classmethod
    def get_gpts_conf(cls, key=None):
        gpts_conf = settings.get_from_db('gpts_conf')
        if key:
            return gpts_conf.get(key)
        return gpts_conf

    @classmethod
    def get_llm_conf(cls, llm_name: str) -> dict:
        llm_list = cls.get_gpts_conf('llms')
        for one in llm_list:
            if one['model_name'] == llm_name:
                return one.copy()
        return llm_list[0].copy()
