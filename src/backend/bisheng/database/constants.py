from enum import Enum

# 默认普通用户角色的ID
DefaultRole = 2
# 超级管理员角色ID
AdminRole = 1


# 消息表里一些基础的category类型
class MessageCategory(Enum):
    QUESTION = 'question'  # 用户问题
    ANSWER = 'answer'  # 答案
