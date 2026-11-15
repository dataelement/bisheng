from .base import BaseErrorCode


#  Return error code related to the knowledge base module, function module code:109
class KnowledgeExistError(BaseErrorCode):
    Code: int = 10900
    Msg: str = "Duplicate Knowledge Base Name"


class KnowledgeNoEmbeddingError(BaseErrorCode):
    Code: int = 10901
    Msg: str = "Knowledge Base must select oneembeddingModels"


class KnowledgeEmbeddingUnavailableError(BaseErrorCode):
    Code: int = 10903
    Msg: str = (
        'The embedding model for knowledge base "{knowledge_name}" is unavailable. Please check its configuration.'
    )


class KnowledgeLLMError(BaseErrorCode):
    Code: int = 10902
    Msg: str = "Documentation Knowledge Base Summary Model is no longer valid, please go to Model Management-Configure in System Model Settings.{exception}"


class KnowledgeChunkError(BaseErrorCode):
    Code: int = 10910
    Msg: str = "The current Knowledge Base version does not support modifying segments, please create a new Knowledge Base and modify segments"


class KnowledgeFileEmptyError(BaseErrorCode):
    Code: int = 10911
    Msg: str = "File resolution is empty"


class KnowledgeFileChunkMaxError(BaseErrorCode):
    Code: int = 10912
    Msg: str = "Segmentation results are too long, try using more splitters in your custom strategy (ex. \\n、。、\\.) for segmentation"


class KnowledgeFileDamagedError(BaseErrorCode):
    Code: int = 10913
    Msg: str = "The file may be corrupted and cannot be parsed, please check and upload again"


class KnowledgeFileNotSupportedError(BaseErrorCode):
    Code: int = 10914
    Msg: str = "Parsing of this type of file is not supported, please check and upload again"


class KnowledgeEtl4lmTimeoutError(BaseErrorCode):
    Code: int = 10915
    Msg: str = "etl4lmService busy, please upgradeetl4lmComputing power of the service"


class KnowledgeExcelChunkMaxError(BaseErrorCode):
    Code: int = 10916
    Msg: str = (
        "Segmentation results are too long, try reducing the number of table segmentation rows in your custom strategy"
    )


class OfdConvertError(BaseErrorCode):
    Code: int = 10917
    Msg: str = "OFD file is corrupted or has an invalid format"


class KnowledgeSimilarError(BaseErrorCode):
    Code: int = 10920
    Msg: str = "Not configuredQAKnowledge Base Similarity Question Model"


class KnowledgeQAError(BaseErrorCode):
    Code: int = 10930
    Msg: str = "This issue already exists"


class KnowledgeCPError(BaseErrorCode):
    Code: int = 10940
    Msg: str = "A file is currently being parsed and cannot be copied"


class KnowledgeCPEmptyError(BaseErrorCode):
    Code: int = 10941
    Msg: str = "Knowledge Base content is empty and cannot be copied"


# Multiple knowledge base files are not supported for simultaneous deletion
class KnowledgeFileDeleteError(BaseErrorCode):
    Code: int = 10950
    Msg: str = "Multiple knowledge base files are not supported for simultaneous deletion"


class KnowledgeRebuildingError(BaseErrorCode):
    Code: int = 10951
    Msg: str = "Knowledge base is being rebuilt, modifications are not allowedembeddingModels"


class KnowledgePreviewError(BaseErrorCode):
    Code: int = 10952
    Msg: str = "Document parsing failed"  # Failed to parse preview file


class KnowledgeFileFailedError(BaseErrorCode):
    Code: int = 10953
    Msg: str = "File parsing failed: {exception}"


class KnowledgeMediaTranscriptionError(BaseErrorCode):
    Code: int = 10954
    Msg: str = "Media transcription failed"


class KnowledgeMediaNoRecognizableAudioError(BaseErrorCode):
    Code: int = 10956
    Msg: str = "No recognizable audio detected"


class KnowledgeWebLinkImportError(BaseErrorCode):
    Code: int = 10955
    Msg: str = "Web link import failed"


# Is notQAThe knowledge base upon
class KnowledgeNotQAError(BaseErrorCode):
    Code: int = 10960
    Msg: str = "Is notQAThe knowledge base upon"


class KnowledgeRecommendQuestionError(BaseErrorCode):
    Code: int = 10961
    Msg: str = "The model returned an incorrect format: {message}"


# F030: resource type not supported by the v2 unified filelib API
# (illegal type value, or personal knowledge base type=2 which is not exposed externally)
class KnowledgeTypeNotSupportedError(BaseErrorCode):
    Code: int = 10962
    Msg: str = "Unsupported knowledge resource type"


# Knowledge base does not exist
class KnowledgeNotExistError(BaseErrorCode):
    Code: int = 10970
    Msg: str = "Knowledge base does not exist"


# Knowledge base file does not exist
class KnowledgeFileNotExistError(BaseErrorCode):
    Code: int = 10971
    Msg: str = "Knowledge base file does not exist"


class KnowledgeTenantMismatchError(BaseErrorCode):
    Code: int = 10972
    Msg: str = "当前租户与知识库归属租户不一致，暂不支持上传文件，请切换到知识库所属租户后重试"


# Conflicts with built-in metadata field name
class KnowledgeMetadataFieldConflictError(BaseErrorCode):
    Code: int = 10980
    Msg: str = "{field_name} Conflicts with built-in metadata field name"


# Metadata field already exists
class KnowledgeMetadataFieldExistError(BaseErrorCode):
    Code: int = 10981
    Msg: str = "Meta data fields {field_name} already exists"


# Metadata field does not exist
class KnowledgeMetadataFieldNotExistError(BaseErrorCode):
    Code: int = 10982
    Msg: str = "Meta data fields {field_name} Does not exist"


# Built-in metadata fields cannot be modified
class KnowledgeMetadataFieldImmutableError(BaseErrorCode):
    Code: int = 10983
    Msg: str = "Built-in metadata fields {field_name} Cannot be modified"


# Metadata value type conversion error
class KnowledgeMetadataValueTypeConvertError(BaseErrorCode):
    Code: int = 10984
    Msg: str = "Meta data fields {field_name} Value type conversion error: {error_msg}"


# 标签已存在
class KnowledgeTagExistError(BaseErrorCode):
    Code: int = 10985
    Msg: str = "标签已存在"


# 标签不存在
class KnowledgeTagNotExistError(BaseErrorCode):
    Code: int = 10986
    Msg: str = "标签不存在"


# 单个文件标签数量超出限制
class KnowledgeFileTagLimitError(BaseErrorCode):
    Code: int = 10987
    Msg: str = "每个文件最多只能关联 5 个标签"


class KnowledgeSpaceTagLibraryNotExistError(BaseErrorCode):
    Code: int = 10988
    Msg: str = "标签库不存在"


class KnowledgeSpaceTagLibraryInvalidError(BaseErrorCode):
    Code: int = 10989
    Msg: str = "标签库无效"


# source keyword Processing in the background, try again later
class BackendProcessingError(BaseErrorCode):
    Code = 10990
    Msg = "Processing in the background, try again later"


# F027: cursor-based pagination — cursor parsing/version/context/key-length failed
class KnowledgeInvalidCursorError(BaseErrorCode):
    Code: int = 10991
    Msg: str = "Invalid pagination cursor"


# F048 visible-first refactor: /api/v1/knowledge is for document/QA libraries
# (knowledge_library) only. Knowledge spaces have their own list endpoints,
# and previously this handler returned an empty page for ordinary users but
# the full set for super admins because super_admin short-circuited before the
# resource-type mismatch was detected. Reject SPACE explicitly so both roles
# see the same error.
class KnowledgeSpaceListNotSupportedError(BaseErrorCode):
    Code: int = 10992
    Msg: str = "This endpoint does not list knowledge spaces; use the knowledge-space endpoints instead"


class KnowledgeCreationScopeChangedError(BaseErrorCode):
    Code: int = 10993
    Msg: str = "Your tenant has changed; reopen the knowledge-base creation form"


class KnowledgeUnificationError(BaseErrorCode):
    """F118 errors keep v1 envelopes and declare an explicit v2 transport status."""

    http_status: int = 409


class ReferenceCoverageNotReadyError(KnowledgeUnificationError):
    Code: int = 10994
    Msg: str = "Reference coverage is not ready; the operation cannot be checked completely"
    http_status: int = 503


class ResourceReferenceConflictError(KnowledgeUnificationError):
    Code: int = 10995
    Msg: str = "The resource is referenced by saved business configuration"


class ResourceReferenceInvalidError(KnowledgeUnificationError):
    Code: int = 10996
    Msg: str = "A saved resource reference is invalid or its revision has changed"


class KnowledgeProcessingObsoleteError(KnowledgeUnificationError):
    Code: int = 10997
    Msg: str = "The task is obsolete because its business model or index configuration changed"


class KnowledgeOperationPlanConflictError(KnowledgeUnificationError):
    Code: int = 10998
    Msg: str = "The operation no longer matches its frozen reference plan"


class KnowledgeProcessingConflictError(KnowledgeUnificationError):
    Code: int = 10999
    Msg: str = "A conflicting operation is processing this resource"


class KnowledgeProcessingSettingsConflictError(KnowledgeUnificationError):
    Code: int = 18082
    Msg: str = "Processing defaults have changed; reload before saving"


class KnowledgeProcessingJobNotFoundError(KnowledgeUnificationError):
    Code: int = 18083
    Msg: str = "The processing task does not exist or is not accessible"
    http_status: int = 404


class KnowledgeProcessingJobNotRetryableError(KnowledgeUnificationError):
    Code: int = 18084
    Msg: str = "The processing task cannot be retried in its current state"


class KnowledgeIdempotencyConflictError(KnowledgeUnificationError):
    Code: int = 18085
    Msg: str = "The idempotency key was already used for a different request"


class KnowledgeOperationConfirmationRequiredError(KnowledgeUnificationError):
    Code: int = 18086
    Msg: str = "Review and confirm the operation before executing it"


class KnowledgeOperationPlanChangedError(KnowledgeUnificationError):
    Code: int = 18087
    Msg: str = "The operation impact has changed; review and confirm it again"


class KnowledgeOperationPlanExpiredError(KnowledgeUnificationError):
    Code: int = 18088
    Msg: str = "The operation confirmation has expired; review it again"
