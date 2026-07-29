from .base import BaseErrorCode


# Dictionary module error codes: 191xx
class DictionaryNotFoundError(BaseErrorCode):
    """字典条目不存在"""

    Code: int = 19100
    Msg: str = "Dictionary entry does not exist"


class DictionaryDuplicateError(BaseErrorCode):
    """同一租户下相同类型的字典取值已存在"""

    Code: int = 19101
    Msg: str = "Dictionary entry already exists"


class DictionaryPermissionDeniedError(BaseErrorCode):
    """仅管理员可维护字典"""

    Code: int = 19102
    Msg: str = "Only administrators can manage dictionary entries"


class DictionaryExportEmptyError(BaseErrorCode):
    """无可导出的字典数据"""

    Code: int = 19103
    Msg: str = "No dictionary data available for export"


class DictionaryImportFileEmptyError(BaseErrorCode):
    """导入文件为空"""

    Code: int = 19104
    Msg: str = "Imported file is empty"


class DictionaryImportFormatError(BaseErrorCode):
    """导入文件格式不正确"""

    Code: int = 19105
    Msg: str = "Imported file format is not supported, please upload xlsx or xls"


class DictionaryImportParseError(BaseErrorCode):
    """Excel 解析失败"""

    Code: int = 19106
    Msg: str = "Failed to parse Excel file"


class DictionaryImportHeaderError(BaseErrorCode):
    """导入模板列不匹配"""

    Code: int = 19107
    Msg: str = "Imported Excel header does not match the required template"


class DictionaryImportTypeInvalidError(BaseErrorCode):
    """导入类型值无效"""

    Code: int = 19108
    Msg: str = "Invalid dictionary type value in imported Excel"


class DictionaryImportRowError(BaseErrorCode):
    """导入行数据错误(用于携带行号信息)"""

    Code: int = 19109
    Msg: str = "Row {row} import failed: {reason}"
