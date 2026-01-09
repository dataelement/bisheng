# QAModule-related return error codes 140 What/the beginning?
from .base import BaseErrorCode


# Processing in the background, try again later
class BackendProcessingError(BaseErrorCode):
    Code = 14001
    Msg = "Processing in the background, try again later"
