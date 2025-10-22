# 模块用的一些常量或枚举
from enum import Enum


# 服务提供方枚举
class LLMServerType(Enum):
    OPENAI = 'openai'
    AZURE_OPENAI = 'azure_openai'
    OLLAMA = 'ollama'
    XINFERENCE = 'xinference'
    LLAMACPP = 'llamacpp'
    VLLM = 'vllm'
    QWEN = 'qwen'  # 阿里通义千问
    QIAN_FAN = 'qianfan'  # 百度千帆
    ZHIPU = 'zhipu'  # 智谱清言
    MINIMAX = 'minimax'
    ANTHROPIC = 'anthropic'
    DEEPSEEK = 'deepseek'
    SPARK = 'spark'  # 讯飞星火大模型
    BISHENG_RT = 'bisheng_rt'
    TENCENT = 'tencent'  # 腾讯云
    MOONSHOT = 'moonshot'  # 月之暗面的kimi
    VOLCENGINE = 'volcengine'  # 火山引擎的大模型
    SILICON = 'silicon'  # 硅基流动
    MIND_IE = 'MindIE'  # 昇腾推理引擎 MindIE


# 模型类型枚举
class LLMModelType(Enum):
    LLM = 'llm'
    EMBEDDING = 'embedding'
    RERANK = 'rerank'
    ASR = 'asr'
    TTS = 'tts'


class LLMModelStatus(Enum):
    NORMAL = 0  # 正常
    ERROR = 1  # 异常
    UNKNOWN = 2  # 未知
