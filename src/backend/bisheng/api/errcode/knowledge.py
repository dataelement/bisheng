from bisheng.api.errcode.base import BaseErrorCode


#  知识库模块相关的返回错误码，功能模块代码：109
class KnowledgeExistError(BaseErrorCode):
    Code: int = 10900
    Msg: str = '知识库名称重复'

