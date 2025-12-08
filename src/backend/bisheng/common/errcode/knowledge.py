from .base import BaseErrorCode


#  知识库模块相关的返回错误码，功能模块代码：109
class KnowledgeExistError(BaseErrorCode):
    Code: int = 10900
    Msg: str = '知识库名称重复'


class KnowledgeNoEmbeddingError(BaseErrorCode):
    Code: int = 10901
    Msg: str = '知识库必须选择一个embedding模型'


class KnowledgeLLMError(BaseErrorCode):
    Code: int = 10902
    Msg: str = '文档知识库总结模型已失效，请前往模型管理-系统模型设置中进行配置。{exception}'


class KnowledgeChunkError(BaseErrorCode):
    Code: int = 10910
    Msg: str = '当前知识库版本不支持修改分段，请创建新知识库后进行分段修改'


class KnowledgeFileEmptyError(BaseErrorCode):
    Code: int = 10911
    Msg: str = '文件解析为空'


class KnowledgeFileChunkMaxError(BaseErrorCode):
    Code: int = 10912
    Msg: str = '分段结果超长，请尝试在自定义策略中使用更多切分符（例如 \\n、。、\\.）进行切分'


class KnowledgeFileDamagedError(BaseErrorCode):
    Code: int = 10913
    Msg: str = '文件可能已损坏，无法解析，请检查后重新上传'


class KnowledgeFileNotSupportedError(BaseErrorCode):
    Code: int = 10914
    Msg: str = '不支持该类型文件的解析，请检查后重新上传'


class KnowledgeEtl4lmTimeoutError(BaseErrorCode):
    Code: int = 10915
    Msg: str = 'etl4lm服务繁忙，请升级etl4lm服务的算力'


class KnowledgeSimilarError(BaseErrorCode):
    Code: int = 10920
    Msg: str = '未配置QA知识库相似问模型'


class KnowledgeQAError(BaseErrorCode):
    Code: int = 10930
    Msg: str = '该问题已存在'


class KnowledgeCPError(BaseErrorCode):
    Code: int = 10940
    Msg: str = '当前有文件正在解析，不可复制'


# 不支持多个知识库的文件同时删除
class KnowledgeFileDeleteError(BaseErrorCode):
    Code: int = 10950
    Msg: str = '不支持多个知识库的文件同时删除'


class KnowledgeRebuildingError(BaseErrorCode):
    Code: int = 10951
    Msg: str = '知识库重新构建中，不允许修改embedding模型'


class KnowledgePreviewError(BaseErrorCode):
    Code: int = 10952
    Msg: str = '文档解析失败'  # 预览文件解析失败


# 不是QA知识库
class KnowledgeNotQAError(BaseErrorCode):
    Code: int = 10960
    Msg: str = '不是QA知识库'


# 知识库不存在
class KnowledgeNotExistError(BaseErrorCode):
    Code: int = 10970
    Msg: str = '知识库不存在'


# 知识库文件不存在
class KnowledgeFileNotExistError(BaseErrorCode):
    Code: int = 10971
    Msg: str = '知识库文件不存在'


# 与内置元数据字段名称冲突
class KnowledgeMetadataFieldConflictError(BaseErrorCode):
    Code: int = 10980
    Msg: str = '{field_name} 与内置元数据字段名称冲突'


# 元数据字段已存在
class KnowledgeMetadataFieldExistError(BaseErrorCode):
    Code: int = 10981
    Msg: str = '元数据字段 {field_name} 已存在'


# 元数据字段不存在
class KnowledgeMetadataFieldNotExistError(BaseErrorCode):
    Code: int = 10982
    Msg: str = '元数据字段 {field_name} 不存在'


# 不能修改内置元数据字段
class KnowledgeMetadataFieldImmutableError(BaseErrorCode):
    Code: int = 10983
    Msg: str = '内置元数据字段 {field_name} 不能修改'


# 元数据值类型转换错误
class KnowledgeMetadataValueTypeConvertError(BaseErrorCode):
    Code: int = 10984
    Msg: str = '元数据字段 {field_name} 值类型转换错误: {error_msg}'
