from enum import Enum


class StatusEnum(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


# Generalized application type enumeration
class ApplicationTypeEnum(str, Enum):
    """App Type Enumeration"""

    # Workflow Apps
    WORKFLOW = "workflow"
    # Assistant App
    ASSISTANT = "assistant"
    # Inspiration App
    LINSIGHT = "linsight"
    # Daily Conversation App
    DAILY_CHAT = "daily_chat"
    # Knowledge Base Application
    KNOWLEDGE_BASE = "knowledge_base"
    KNOWLEDGE_SPACE = "knowledge_space"
    # RAGBack
    RAG_TRACEABILITY = "rag_traceability"
    # Review Apps
    EVALUATION = "evaluation"
    # Model Connectivity Testing
    MODEL_TEST = "model_test"
    # ASR
    ASR = "asr"
    # TTS
    TTS = "tts"

    UNKNOWN = "unknown"


class BaseTelemetryTypeEnum(str, Enum):
    """Basic Telemetry Event Type Enumeration"""

    # User Login Events
    USER_LOGIN = "user_login"

    # Tool Call Event
    TOOL_INVOKE = "tool_invoke"

    # Add Session Event
    NEW_MESSAGE_SESSION = "new_message_session"

    # File Parsing Event
    FILE_PARSE = "file_parse"

    # Delete Session Event
    DELETE_MESSAGE_SESSION = "delete_message_session"

    # New App Event
    NEW_APPLICATION = "new_application"

    # Edit App Event
    EDIT_APPLICATION = "edit_application"

    # Delete app event
    DELETE_APPLICATION = "delete_application"

    # Add Knowledge Base Event
    NEW_KNOWLEDGE_BASE = "new_knowledge_base"

    # Delete Knowledge Base Event
    DELETE_KNOWLEDGE_BASE = "delete_knowledge_base"

    # Knowledge Base File Upload Event
    NEW_KNOWLEDGE_FILE = "new_knowledge_file"

    # Knowledge Base File Delete Event
    DELETE_KNOWLEDGE_FILE = "delete_knowledge_file"

    # Session Message Feedback Event
    MESSAGE_FEEDBACK = "message_feedback"

    # Model Call Event
    MODEL_INVOKE = "model_invoke"

    # Number of online sessions
    APPLICATION_ALIVE = "application_alive"

    # Session Run Time
    APPLICATION_PROCESS = "application_process"

    # Shougang portal favorite success event
    PORTAL_FAVORITE = "portal_favorite"

    # Shougang portal QA success event
    PORTAL_QA = "portal_qa"

    # Shougang portal document preview/read success event
    PORTAL_DOCUMENT_READ = "portal_document_read"

    # Shougang portal document download event
    PORTAL_DOCUMENT_DOWNLOAD = "portal_document_download"
