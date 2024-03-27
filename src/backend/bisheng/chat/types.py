from enum import Enum


# client的业务类型
class WorkType(Enum):
    # 技能会话业务
    FLOW = 'flow'
    # 助手会话业务
    GPTS = 'assistant'
