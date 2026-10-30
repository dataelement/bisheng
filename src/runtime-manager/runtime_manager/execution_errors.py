"""Execution failures shared by the control plane and lightweight workers."""


class ExecutionError(RuntimeError):
    def __init__(self, reason, tail=""):
        super().__init__(reason)
        self.tail = tail
