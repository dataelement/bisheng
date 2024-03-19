from typing import List

from bisheng.settings import settings
from pydantic import BaseModel


class Settings(BaseModel):
    authjwt_secret_key: str = settings.jwt_secret
    # Configure application to store and get JWT from cookies
    authjwt_token_location: List[str] = ['cookies', 'headers']
    # Disable CSRF Protection for this example. default is True
    authjwt_cookie_csrf_protect: bool = False
