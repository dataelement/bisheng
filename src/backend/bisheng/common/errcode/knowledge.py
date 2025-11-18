from .base import BaseErrorCode


#  知识库模块相关的返回错误码，功能模块代码：109
class KnowledgeExistError(BaseErrorCode):
    Code: int = 10900
    Msg: str = '知识库名称重复'


class KnowledgeNoEmbeddingError(BaseErrorCode):
    Code: int = 10901
    Msg: str = '知识库必须选择一个embedding模型'


class KnowledgeChunkError(BaseErrorCode):
    Code: int = 10910
    Msg: str = '当前知识库版本不支持修改分段，请创建新知识库后进行分段修改'


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
