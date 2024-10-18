from enum import Enum


class WorkflowStatus(Enum):
    RUNNING = 'RUNNING'
    SUCCESS = 'SUCCESS'
    FAILED = 'FAILED'
    INPUT = 'INPUT'
