from enum import Enum


class BaseTelemetryTypeEnum(str, Enum):
    """基础的遥测事件类型枚举"""

    # 用户登录事件
    USER_LOGIN = "user_login"

    # 新增会话事件
    NEW_MESSAGE_SESSION = "new_message_session"

