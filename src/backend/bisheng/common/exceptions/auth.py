class AuthJWTException(Exception):
    """
    Base except which all fastapi_jwt_auth errors extend
    """
    pass


class JWTDecodeError(AuthJWTException):
    """
    An error decoding a JWT
    """

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
