from .base import BaseErrorCode


class BrowserObjectBucketError(BaseErrorCode):
    """A browser path was requested for a bucket the site entrance does not serve."""

    Code: int = 11301
    Msg: str = "This bucket cannot be opened in the browser"
