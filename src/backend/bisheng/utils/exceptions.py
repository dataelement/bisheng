class IgnoreException(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return self.message


# For business exception throwing error message
class MessageException(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return self.message


class FileParseException(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return self.message


class EtlException(Exception):
    def __init__(self, message, *, http_status=None, operation=None):
        self.http_status = http_status
        self.operation = operation
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return self.message
