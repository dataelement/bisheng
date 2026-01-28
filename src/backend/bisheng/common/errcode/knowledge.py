from .base import BaseErrorCode


#  Return error code related to the knowledge base module, function module code:109
class KnowledgeExistError(BaseErrorCode):
    Code: int = 10900
    Msg: str = 'Duplicate Knowledge Base Name'


class KnowledgeNoEmbeddingError(BaseErrorCode):
    Code: int = 10901
    Msg: str = 'Knowledge Base must select oneembeddingModels'


class KnowledgeLLMError(BaseErrorCode):
    Code: int = 10902
    Msg: str = 'Documentation Knowledge Base Summary Model is no longer valid, please go to Model Management-Configure in System Model Settings.{exception}'


class KnowledgeChunkError(BaseErrorCode):
    Code: int = 10910
    Msg: str = 'The current Knowledge Base version does not support modifying segments, please create a new Knowledge Base and modify segments'


class KnowledgeFileEmptyError(BaseErrorCode):
    Code: int = 10911
    Msg: str = 'File resolution is empty'


class KnowledgeFileChunkMaxError(BaseErrorCode):
    Code: int = 10912
    Msg: str = 'Segmentation results are too long, try using more splitters in your custom strategy (ex. \\n、。、\\.) for segmentation'


class KnowledgeFileDamagedError(BaseErrorCode):
    Code: int = 10913
    Msg: str = 'The file may be corrupted and cannot be parsed, please check and upload again'


class KnowledgeFileNotSupportedError(BaseErrorCode):
    Code: int = 10914
    Msg: str = 'Parsing of this type of file is not supported, please check and upload again'


class KnowledgeEtl4lmTimeoutError(BaseErrorCode):
    Code: int = 10915
    Msg: str = 'etl4lmService busy, please upgradeetl4lmComputing power of the service'


class KnowledgeExcelChunkMaxError(BaseErrorCode):
    Code: int = 10916
    Msg: str = 'Segmentation results are too long, try reducing the number of table segmentation rows in your custom strategy'


class KnowledgeSimilarError(BaseErrorCode):
    Code: int = 10920
    Msg: str = 'Not configuredQAKnowledge Base Similarity Question Model'


class KnowledgeQAError(BaseErrorCode):
    Code: int = 10930
    Msg: str = 'This issue already exists'


class KnowledgeCPError(BaseErrorCode):
    Code: int = 10940
    Msg: str = 'A file is currently being parsed and cannot be copied'


class KnowledgeCPEmptyError(BaseErrorCode):
    Code: int = 10941
    Msg: str = 'Knowledge Base content is empty and cannot be copied'


# Multiple knowledge base files are not supported for simultaneous deletion
class KnowledgeFileDeleteError(BaseErrorCode):
    Code: int = 10950
    Msg: str = 'Multiple knowledge base files are not supported for simultaneous deletion'


class KnowledgeRebuildingError(BaseErrorCode):
    Code: int = 10951
    Msg: str = 'Knowledge base is being rebuilt, modifications are not allowedembeddingModels'


class KnowledgePreviewError(BaseErrorCode):
    Code: int = 10952
    Msg: str = 'Document parsing failed'  # Failed to parse preview file


class KnowledgeFileFailedError(BaseErrorCode):
    Code: int = 10953
    Msg: str = 'File parsing failed: {exception}'


# Is notQAThe knowledge base upon
class KnowledgeNotQAError(BaseErrorCode):
    Code: int = 10960
    Msg: str = 'Is notQAThe knowledge base upon'


class KnowledgeRecommendQuestionError(BaseErrorCode):
    Code: int = 10961
    Msg: str = 'The model returned an incorrect format: {message}'


# Knowledge base does not exist
class KnowledgeNotExistError(BaseErrorCode):
    Code: int = 10970
    Msg: str = 'Knowledge base does not exist'


# Knowledge base file does not exist
class KnowledgeFileNotExistError(BaseErrorCode):
    Code: int = 10971
    Msg: str = 'Knowledge base file does not exist'


# Conflicts with built-in metadata field name
class KnowledgeMetadataFieldConflictError(BaseErrorCode):
    Code: int = 10980
    Msg: str = '{field_name} Conflicts with built-in metadata field name'


# Metadata field already exists
class KnowledgeMetadataFieldExistError(BaseErrorCode):
    Code: int = 10981
    Msg: str = 'Meta data fields {field_name} already exists'


# Metadata field does not exist
class KnowledgeMetadataFieldNotExistError(BaseErrorCode):
    Code: int = 10982
    Msg: str = 'Meta data fields {field_name} Does not exist'


# Built-in metadata fields cannot be modified
class KnowledgeMetadataFieldImmutableError(BaseErrorCode):
    Code: int = 10983
    Msg: str = 'Built-in metadata fields {field_name} Cannot be modified'


# Metadata value type conversion error
class KnowledgeMetadataValueTypeConvertError(BaseErrorCode):
    Code: int = 10984
    Msg: str = 'Meta data fields {field_name} Value type conversion error: {error_msg}'
