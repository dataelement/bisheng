from bisheng.common.errcode import BaseErrorCode


class ToolTypeRepeatError(BaseErrorCode):
    Code: int = 15000
    Msg: str = 'Tool name already exists'


class ToolTypeEmptyError(BaseErrorCode):
    Code: int = 15001
    Msg: str = 'Under the toolAPITidak boleh kosong.'


class ToolTypeNotExistsError(BaseErrorCode):
    Code: int = 15002
    Msg: str = 'Tool does not exist.'


class ToolTypeNameError(BaseErrorCode):
    Code: int = 15003
    Msg: str = 'Name does not meet specification: at least1characters, cannot exceed1000characters'


class ToolTypeIsPresetError(BaseErrorCode):
    Code: int = 15010
    Msg: str = 'Preset tool category cannot be deleted'


class ToolSchemaDownloadError(BaseErrorCode):
    Code: int = 15020
    Msg: str = 'ToolsSchemaright of privacyurlDownload failed'


class ToolSchemaEmptyError(BaseErrorCode):
    Code: int = 15021
    Msg: str = 'ToolsSchemaTidak boleh kosong.'


class ToolSchemaParseError(BaseErrorCode):
    Code: int = 15022
    Msg: str = 'openapi schemaError parsing, please check if the content matchesjsonoryamlFormat: {exception}'


class ToolSchemaServerError(BaseErrorCode):
    Code: int = 15023
    Msg: str = 'serverhitting the nail on the headurlMust start withhttporhttpsWhat/the beginning?: {url}'


class ToolMcpSchemaError(BaseErrorCode):
    Code: int = 15024
    Msg: str = 'mcpTool configuration parsing failed, please check if the content matchesmcpConfigure Format: {exception}'
