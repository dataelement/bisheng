"""OpenFGA client exceptions."""


class FGAClientError(Exception):
    """Base exception for all OpenFGA client errors."""


class FGAConnectionError(FGAClientError):
    """OpenFGA server is unreachable or timed out."""


class FGAWriteError(FGAClientError):
    """Failed to write/delete tuples."""


class FGAModelError(FGAClientError):
    """Failed to write or read authorization model."""
