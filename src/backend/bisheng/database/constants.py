from enum import Enum

# Default Normal User Role'sID
DefaultRole = 2
# Super Admin RoleID
AdminRole = 1


# Some of the basiccategoryType
class MessageCategory(Enum):
    QUESTION = 'question'  # User Questions
    ANSWER = 'answer'  # Answers
