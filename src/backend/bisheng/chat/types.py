from enum import Enum


# clientBusiness Type
class WorkType(Enum):
    # Skills Conversation Business
    FLOW = 'flow'
    # Assistant Conversation Business
    GPTS = 'assistant'
    # workflow in terms of business,
    WORKFLOW = 'workflow'


class IgnoreException(Exception):
    """ dont`t need print traceback stack """

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return self.message
