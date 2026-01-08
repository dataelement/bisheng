# Some constants or enums for the module
from enum import Enum


# Service Provider Enumeration
class LLMServerType(Enum):
    OPENAI = 'openai'
    AZURE_OPENAI = 'azure_openai'
    OLLAMA = 'ollama'
    XINFERENCE = 'xinference'
    LLAMACPP = 'llamacpp'
    VLLM = 'vllm'
    QWEN = 'qwen'  # Ali Tongyi Qianqian
    QIAN_FAN = 'qianfan'  # Baidu Qianfan
    ZHIPU = 'zhipu'  # Zhi Spectrum Qing Yan
    MINIMAX = 'minimax'
    ANTHROPIC = 'anthropic'
    DEEPSEEK = 'deepseek'
    SPARK = 'spark'  # Xunfei Starfire Large Model
    BISHENG_RT = 'bisheng_rt'
    TENCENT = 'tencent'  # Tencent Cloud
    MOONSHOT = 'moonshot'  # Dark Side of the Moonkimi
    VOLCENGINE = 'volcengine'  # Large model of a volcanic engine
    SILICON = 'silicon'  # Silicon-based flow
    MIND_IE = 'MindIE'  # Ascendant Inference Engine MindIE


# Model Type Enumeration
class LLMModelType(Enum):
    LLM = 'llm'
    EMBEDDING = 'embedding'
    RERANK = 'rerank'
    ASR = 'asr'
    TTS = 'tts'


class LLMModelStatus(Enum):
    NORMAL = 0  # Normal
    ERROR = 1  # Abnormal
    UNKNOWN = 2  # Unknown
