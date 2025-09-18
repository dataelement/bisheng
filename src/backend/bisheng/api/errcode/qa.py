# QA模块相关的返回错误码 140 开头

# 后台处理中，稍后再试
class BackendProcessingError(Exception):
    code = 14001
    msg = "后台处理中，稍后再试"
