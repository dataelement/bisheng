from bisheng.common.errcode.base import BaseErrorCode


class SopFileError(BaseErrorCode):
    Code: int = 11010
    Msg: str = 'SOP文件格式不符合要求'


class SopShowcaseError(BaseErrorCode):
    Code: int = 11011
    Msg: str = 'SOP设置精选案例失败'


class FileUploadError(BaseErrorCode):
    __doc__ = 'Linsight上传文件失败'
    Code: int = 11020
    Msg: str = '文件上传失败'


# 您的灵思使用次数已用完，请使用新的邀请码激活灵思功能
class LinsightUseUpError(BaseErrorCode):
    Code: int = 11030
    Msg: str = '您的灵思使用次数已用完，请使用新的邀请码激活灵思功能'


# 提交灵思用户问题失败
class LinsightQuestionError(BaseErrorCode):
    Code: int = 11040
    Msg: str = '提交灵思用户问题失败'


# 请联系管理员检查工作台向量检索模型状态
class LinsightVectorModelError(BaseErrorCode):
    Code: int = 11050
    Msg: str = '请联系管理员检查工作台向量检索模型状态'


# 指导手册检索失败，向量检索与关键词检索均不可用
class LinsightDocSearchError(BaseErrorCode):
    Code: int = 11060
    Msg: str = '指导手册检索失败，向量检索与关键词检索均不可用'


# 指导手册检索失败
class LinsightDocNotFoundError(BaseErrorCode):
    Code: int = 11070
    Msg: str = '指导手册检索失败'


# 初始化灵思工作台工具失败
class LinsightToolInitError(BaseErrorCode):
    Code: int = 11080
    Msg: str = '初始化灵思工作台工具失败'


# 灵思Bisheng LLM相关错误
class LinsightBishengLLMError(BaseErrorCode):
    Code: int = 11090
    Msg: str = '灵思Bisheng LLM相关错误'


# 生成SOP内容失败
class LinsightGenerateSopError(BaseErrorCode):
    Code: int = 11100
    Msg: str = '生成SOP内容失败'


# 修改SOP内容失败
class LinsightModifySopError(BaseErrorCode):
    Code: int = 11110
    Msg: str = '修改SOP内容失败'


# 灵思会话版本已完成或正在执行，无法再次执行
class LinsightSessionVersionRunningError(BaseErrorCode):
    Code: int = 11120
    Msg: str = '灵思会话版本已完成或正在执行，无法再次执行'


# 开始执行灵思任务失败
class LinsightStartTaskError(BaseErrorCode):
    Code: int = 11130
    Msg: str = '开始执行灵思任务失败'


# 获取灵思队列排队状态失败
class LinsightQueueStatusError(BaseErrorCode):
    Code: int = 11140
    Msg: str = '获取灵思队列排队状态失败'


# 添加指导手册失败，向量存储添加数据失败
class LinsightAddSopError(BaseErrorCode):
    Code: int = 11150
    Msg: str = '添加指导手册失败，向量存储添加数据失败'


# 更新指导手册失败，向量存储更新数据失败
class LinsightUpdateSopError(BaseErrorCode):
    Code: int = 11160
    Msg: str = '更新指导手册失败，向量存储更新数据失败'


# 删除指导手册失败，向量存储删除数据失败
class LinsightDeleteSopError(BaseErrorCode):
    Code: int = 11170
    Msg: str = '删除指导手册失败，向量存储删除数据失败'


class SopContentOverLimitError(BaseErrorCode):
    Code: int = 11171
    Msg: str = '{sop_name}内容超长'


class InviteCodeInvalidError(BaseErrorCode):
    Code: int = 11180
    Msg: str = '您输入的邀请码无效'


class InviteCodeBindError(BaseErrorCode):
    Code: int = 11190
    Msg: str = '已绑定其他邀请码'
