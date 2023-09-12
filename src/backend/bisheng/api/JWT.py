from pydantic import BaseModel


class Settings(BaseModel):
    authjwt_secret_key: str = 'xI$xO.oN$sC}tC^oQ(fF^nK~dB&uT('
    # Configure application to store and get JWT from cookies
    authjwt_token_location: set = {'cookies'}
    # Disable CSRF Protection for this example. default is True
    authjwt_cookie_csrf_protect: bool = False
