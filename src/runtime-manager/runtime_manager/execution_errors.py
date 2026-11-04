"""Execution failures shared by the control plane and lightweight workers."""


class ExecutionError(RuntimeError):
    def __init__(self, reason, tail="", *, image_role="", image_ref=""):
        super().__init__(reason)
        self.tail = tail
        self.image_role = image_role
        self.image_ref = image_ref
