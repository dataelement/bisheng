from .base import BaseErrorCode


# RTService-related return error code, function module code:100
class NoSftServerError(BaseErrorCode):
    Code: int = 10001
    Msg: str = "not foundSFTSERVICES"


# Invalid nonce
class InvalidOperationError(BaseErrorCode):
    Code: int = 10002
    Msg: str = "Invalid nonce"


# Resource download failed
class ResourceDownloadError(BaseErrorCode):
    Code: int = 10003
    Msg: str = "Resource download failed"


# Knowledge Base Not Configuredembeddingmodel, please set from workbench configuration
class NoEmbeddingModelError(BaseErrorCode):
    Code: int = 10004
    Msg: str = "Knowledge Base Not Configuredembeddingmodel, please set from workbench configuration"


# The knowledge base uponembeddingModel does not exist, please set from workbench configuration
class EmbeddingModelNotExistError(BaseErrorCode):
    Code: int = 10005
    Msg: str = "The knowledge base uponembeddingModel does not exist, please set from workbench configuration"


# The knowledge base uponembeddingWrong model type, please set from workbench configuration
class EmbeddingModelTypeError(BaseErrorCode):
    Code: int = 10006
    Msg: str = "The knowledge base uponembeddingWrong model type, please set from workbench configuration"


# Please contact the administrator to check the status of the workbench vector retrieval model
class EmbeddingModelStatusError(BaseErrorCode):
    Code: int = 10007
    Msg: str = "Please contact the administrator to check the status of the workbench vector retrieval model"


# No bulkpost found in Trashllmmodel config
class NoLlmModelConfigError(BaseErrorCode):
    Code: int = 10008
    Msg: str = "No bulkpost found in Trashllmmodel config"


# llmModel configuration has been deleted, please reconfigure the model
class LlmModelConfigDeletedError(BaseErrorCode):
    Code: int = 10009
    Msg: str = "llmModel configuration has been deleted, please reconfigure the model"


# Service provider configuration has been deleted, please reconfigurellmModels
class LlmProviderDeletedError(BaseErrorCode):
    Code: int = 10010
    Msg: str = "Service provider configuration has been deleted, please reconfigurellmModels"


# Support onlyLLMModel of type, not supported{model_info.model_type}Type of model
class LlmModelTypeError(BaseErrorCode):
    Code: int = 10011
    Msg: str = "Support onlyLLMModel of type, not supported{model_type}Type of model"


# {server_info.name}under{model_info.model_name}The model is offline, please contact the administrator to launch the corresponding model
class LlmModelOfflineError(BaseErrorCode):
    Code: int = 10012
    Msg: str = "{server_name}under{model_name}The model is offline, please contact the administrator to launch the corresponding model"


# InisialisasillmFailed, please check the configuration or contact the administrator.Error message:{e}
class InitLlmError(BaseErrorCode):
    Code: int = 10013
    Msg: str = (
        "InisialisasillmFailed, please check the configuration or contact the administrator.Error message:{exception}"
    )


class NoAsrModelConfigError(BaseErrorCode):
    Code: int = 10014
    Msg: str = 'Knowledge base ASR model is not configured'


class AsrModelConfigDeletedError(BaseErrorCode):
    Code: int = 10015
    Msg: str = 'Knowledge base ASR model configuration has been deleted'


class AsrProviderDeletedError(BaseErrorCode):
    Code: int = 10016
    Msg: str = 'Knowledge base ASR provider has been deleted'


class AsrModelTypeError(BaseErrorCode):
    Code: int = 10017
    Msg: str = 'Only ASR-type models are supported for knowledge base media transcription, got {model_type}'


class AsrModelOfflineError(BaseErrorCode):
    Code: int = 10018
    Msg: str = 'Knowledge base ASR model {model_name} under {server_name} is offline'


class InitAsrError(BaseErrorCode):
    Code: int = 10019
    Msg: str = 'Failed to initialize knowledge base ASR. Error: {exception}'


class NoTtsModelConfigError(BaseErrorCode):
    Code: int = 10020
    Msg: str = "No bulkpost found in Trashttsmodel config"


class TtsModelConfigDeletedError(BaseErrorCode):
    Code: int = 10021
    Msg: str = "ttsModel configuration has been deleted, please reconfigure the model"


class TtsProviderDeletedError(BaseErrorCode):
    Code: int = 10022
    Msg: str = "Service provider configuration has been deleted, please reconfigurettsModels"


class TtsModelTypeError(BaseErrorCode):
    Code: int = 10023
    Msg: str = "Support onlyTTSModel of type, not supported{model_type}Type of model"


class TtsModelOfflineError(BaseErrorCode):
    Code: int = 10024
    Msg: str = "{server_name}under{model_name}The model is offline, please contact the administrator to launch the corresponding model"


class InitTtsError(BaseErrorCode):
    Code: int = 10025
    Msg: str = (
        "InisialisasittsFailed, please check the configuration or contact the administrator.Error message:{exception}"
    )


class TtsSynthesisFailedError(BaseErrorCode):
    # Distinct business code (not HTTP 500) so the client shows a localized toast
    # instead of raising the global service-maintenance overlay for a TTS failure.
    Code: int = 10026
    Msg: str = "Speech synthesis failed, please try again later"


class SystemConfigEmptyError(BaseErrorCode):
    Code: int = 10030
    Msg: str = "System configuration cannot be empty"


class SystemConfigInvalidError(BaseErrorCode):
    Code: int = 10031
    Msg: str = "The system configuration format is incorrect, please check the configuration content:{exception}"


class UploadFileEmptyError(BaseErrorCode):
    Code: int = 10040
    Msg: str = "Uploaded file cannot be empty"


class UploadFileExtError(BaseErrorCode):
    Code: int = 10041
    Msg: str = "The upload file format is not supported, please upload a file in the correct format"
