from .base import BaseErrorCode


# RT服务相关的返回错误码，功能模块代码：100
class NoSftServerError(BaseErrorCode):
    Code: int = 10001
    Msg: str = '未找到SFT服务'


# 无效操作
class InvalidOperationError(BaseErrorCode):
    Code: int = 10002
    Msg: str = '无效操作'


# 资源下载失败
class ResourceDownloadError(BaseErrorCode):
    Code: int = 10003
    Msg: str = '资源下载失败'


# 未配置知识库embedding模型，请从工作台配置中设置
class NoEmbeddingModelError(BaseErrorCode):
    Code: int = 10004
    Msg: str = '未配置知识库embedding模型，请从工作台配置中设置'

# 知识库embedding模型不存在，请从工作台配置中设置
class EmbeddingModelNotExistError(BaseErrorCode):
    Code: int = 10005
    Msg: str = '知识库embedding模型不存在，请从工作台配置中设置'

# 知识库embedding模型类型错误，请从工作台配置中设置
class EmbeddingModelTypeError(BaseErrorCode):
    Code: int = 10006
    Msg: str = '知识库embedding模型类型错误，请从工作台配置中设置'

# 请联系管理员检查工作台向量检索模型状态
class EmbeddingModelStatusError(BaseErrorCode):
    Code: int = 10007
    Msg: str = '请联系管理员检查工作台向量检索模型状态'

# 没有找到llm模型配置
class NoLlmModelConfigError(BaseErrorCode):
    Code: int = 10008
    Msg: str = '没有找到llm模型配置'

# llm模型配置已被删除，请重新配置模型
class LlmModelConfigDeletedError(BaseErrorCode):
    Code: int = 10009
    Msg: str = 'llm模型配置已被删除，请重新配置模型'

# 服务提供方配置已被删除，请重新配置llm模型
class LlmProviderDeletedError(BaseErrorCode):
    Code: int = 10010
    Msg: str = '服务提供方配置已被删除，请重新配置llm模型'

# 只支持LLM类型的模型，不支持{model_info.model_type}类型的模型
class LlmModelTypeError(BaseErrorCode):
    Code: int = 10011
    Msg: str = '只支持LLM类型的模型，不支持{model_type}类型的模型'

# {server_info.name}下的{model_info.model_name}模型已下线，请联系管理员上线对应的模型
class LlmModelOfflineError(BaseErrorCode):
    Code: int = 10012
    Msg: str = '{server_name}下的{model_name}模型已下线，请联系管理员上线对应的模型'

# 初始化llm失败，请检查配置或联系管理员。错误信息：{e}
class InitLlmError(BaseErrorCode):
    Code: int = 10013
    Msg: str = '初始化llm失败，请检查配置或联系管理员。错误信息：{exception}'