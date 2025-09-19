# QA模块相关的返回错误码 140 开头
from bisheng.api.errcode.base import BaseErrorCode


# 后台处理中，稍后再试
class BackendProcessingError(BaseErrorCode):
    Code = 14001
    Msg = "后台处理中，稍后再试"
