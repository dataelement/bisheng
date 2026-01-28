from enum import Enum


class WorkflowStatus(Enum):
    WAITING = 'WAITING'  # Waiting for asynchronous task scheduling
    RUNNING = 'RUNNING'
    SUCCESS = 'SUCCESS'
    FAILED = 'FAILED'
    INPUT = 'INPUT'  # Status to be entered
    INPUT_OVER = 'INPUT_OVER'  # Entered status
