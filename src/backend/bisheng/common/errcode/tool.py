from bisheng.common.errcode import BaseErrorCode


class ToolTypeRepeatError(BaseErrorCode):
    Code: int = 15000
    Msg: str = '工具名称已存在'


class ToolTypeEmptyError(BaseErrorCode):
    Code: int = 15001
    Msg: str = '工具下的API不能为空'


class ToolTypeNotExistsError(BaseErrorCode):
    Code: int = 15002
    Msg: str = '工具不存在'


class ToolTypeNameError(BaseErrorCode):
    Code: int = 15003
    Msg: str = '名字不符合规范：至少1个字符，不能超过1000个字符'


class ToolTypeIsPresetError(BaseErrorCode):
    Code: int = 15010
    Msg: str = '预置工具类别不可删除'


class ToolSchemaDownloadError(BaseErrorCode):
    Code: int = 15020
    Msg: str = '工具Schema的url下载失败'


class ToolSchemaEmptyError(BaseErrorCode):
    Code: int = 15021
    Msg: str = '工具Schema不能为空'


class ToolSchemaParseError(BaseErrorCode):
    Code: int = 15022
    Msg: str = 'openapi schema解析报错，请检查内容是否符合json或者yaml格式: {exception}'


class ToolSchemaServerError(BaseErrorCode):
    Code: int = 15023
    Msg: str = 'server中的url必须以http或者https开头: {url}'


class ToolMcpSchemaError(BaseErrorCode):
    Code: int = 15024
    Msg: str = 'mcp工具配置解析失败，请检查内容是否符合mcp配置格式: {exception}'
