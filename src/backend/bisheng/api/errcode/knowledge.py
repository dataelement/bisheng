from bisheng.api.errcode.base import BaseErrorCode


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
    Msg: str = '该问题已被标注过'
