from enum import Enum


# client的业务类型
class WorkType(Enum):
    # 技能会话业务
    FLOW = 'flow'
    # 助手会话业务
    GPTS = 'assistant'
    # workflow 业务
    WORKFLOW = 'workflow'


class IgnoreException(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return self.message
