from enum import Enum


class StatusEnum(str, Enum):
    SUCCESS = 'success'
    FAILED = 'failed'


# 广义应用类型枚举
class ApplicationTypeEnum(str, Enum):
    """应用类型枚举"""

    # 工作流应用
    WORKFLOW = "workflow"
    # 技能应用
    SKILL = "skill"
    # 助手应用
    ASSISTANT = "assistant"
    # 灵思应用
    LINSIGHT = "linsight"
    # 日常对话应用
    DAILY_CHAT = "daily_chat"
    # 知识库应用
    KNOWLEDGE_BASE = "knowledge_base"
    # RAG溯源
    RAG_TRACEABILITY = "rag_traceability"
    # 评测应用
    EVALUATION = "evaluation"
    # 模型连通性测试
    MODEL_TEST = "model_test"
    # ASR
    ASR = "asr"
    # TTS
    TTS = "tts"


class BaseTelemetryTypeEnum(str, Enum):
    """基础的遥测事件类型枚举"""

    # 用户登录事件
    USER_LOGIN = "user_login"

    # 工具调用事件
    TOOL_INVOKE = "tool_invoke"

    # 新增会话事件
    NEW_MESSAGE_SESSION = "new_message_session"

    # 文件解析事件
    FILE_PARSE = "file_parse"

    # 删除会话事件
    DELETE_MESSAGE_SESSION = "delete_message_session"

    # 新建应用事件
    NEW_APPLICATION = "new_application"

    # 编辑应用事件
    EDIT_APPLICATION = "edit_application"

    # 删除应用事件
    DELETE_APPLICATION = "delete_application"

    # 新增知识库事件
    NEW_KNOWLEDGE_BASE = "new_knowledge_base"

    # 删除知识库事件
    DELETE_KNOWLEDGE_BASE = "delete_knowledge_base"

    # 知识库文件上传事件
    NEW_KNOWLEDGE_FILE = "new_knowledge_file"

    # 知识库文件删除事件
    DELETE_KNOWLEDGE_FILE = "delete_knowledge_file"

    # 会话消息反馈事件
    MESSAGE_FEEDBACK = "message_feedback"

    # 模型调用事件
    MODEL_INVOKE = "model_invoke"

    # 在线会话数
    APPLICATION_ALIVE = "application_alive"

    # 会话运行时长
    APPLICATION_PROCESS = "application_process"
