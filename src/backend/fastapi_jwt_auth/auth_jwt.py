import jwt, re, uuid, hmac
from jwt.algorithms import requires_cryptography, has_crypto
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Union, Sequence
from fastapi import Request, Response, WebSocket
from fastapi_jwt_auth.auth_config import AuthConfig
from fastapi_jwt_auth.exceptions import (
    InvalidHeaderError,
    CSRFError,
    JWTDecodeError,
    RevokedTokenError,
    MissingTokenError,
    AccessTokenRequired,
    RefreshTokenRequired,
    FreshTokenRequired
)

class AuthJWT(AuthConfig):
    def __init__(self,req: Request = None, res: Response = None):
        """
        Get jwt header from incoming request or get
        request and response object if jwt in the cookie

        :param req: all incoming request
        :param res: response from endpoint
        """
        if res and self.jwt_in_cookies:
            self._response = res

        if req:
            # get request object when cookies in token location
            if self.jwt_in_cookies:
                self._request = req
            # get jwt in headers when headers in token location
            if self.jwt_in_headers:
                auth = req.headers.get(self._header_name.lower())
                if auth: self._get_jwt_from_headers(auth)

    def _get_jwt_from_headers(self,auth: str) -> "AuthJWT":
        """
        Get token from the headers

        :param auth: value from HeaderName
        """
        header_name, header_type = self._header_name, self._header_type

        parts = auth.split()

        # Make sure the header is in a valid format that we are expecting, ie
        if not header_type:
            # <HeaderName>: <JWT>
            if len(parts) != 1:
                msg = "Bad {} header. Expected value '<JWT>'".format(header_name)
                raise InvalidHeaderError(status_code=422,message=msg)
            self._token = parts[0]
        else:
            # <HeaderName>: <HeaderType> <JWT>
            if not re.match(r"{}\s".format(header_type),auth) or len(parts) != 2:
                msg = "Bad {} header. Expected value '{} <JWT>'".format(header_name,header_type)
                raise InvalidHeaderError(status_code=422,message=msg)
            self._token = parts[1]

    def _get_jwt_identifier(self) -> str:
        return str(uuid.uuid4())

    def _get_int_from_datetime(self,value: datetime) -> int:
        """
        :param value: datetime with or without timezone, if don't contains timezone
                      it will managed as it is UTC
        :return: Seconds since the Epoch
        """
        if not isinstance(value, datetime):  # pragma: no cover
            raise TypeError('a datetime is required')
        return int(value.timestamp())

    def _get_secret_key(self, algorithm: str, process: str) -> str:
        """
        Get key with a different algorithm

        :param algorithm: algorithm for decode and encode token
        :param process: for indicating get key for encode or decode token

        :return: plain text or RSA depends on algorithm
        """
        symmetric_algorithms, asymmetric_algorithms = {"HS256","HS384","HS512"}, requires_cryptography

        if algorithm not in symmetric_algorithms and algorithm not in asymmetric_algorithms:
            raise ValueError("Algorithm {} could not be found".format(algorithm))

        if algorithm in symmetric_algorithms:
            if not self._secret_key:
                raise RuntimeError(
                    "authjwt_secret_key must be set when using symmetric algorithm {}".format(algorithm)
                )

            return self._secret_key

        if algorithm in asymmetric_algorithms and not has_crypto:
            raise RuntimeError(
                "Missing dependencies for using asymmetric algorithms. run 'pip install fastapi-jwt-auth[asymmetric]'"
            )

        if process == "encode":
            if not self._private_key:
                raise RuntimeError(
                    "authjwt_private_key must be set when using asymmetric algorithm {}".format(algorithm)
                )

            return self._private_key

        if process == "decode":
            if not self._public_key:
                raise RuntimeError(
                    "authjwt_public_key must be set when using asymmetric algorithm {}".format(algorithm)
                )

            return self._public_key

    def _create_token(
        self,
        subject: Union[str,int],
        type_token: str,
        exp_time: Optional[int],
        fresh: Optional[bool] = False,
        algorithm: Optional[str] = None,
        headers: Optional[Dict] = None,
        issuer: Optional[str] = None,
        audience: Optional[Union[str,Sequence[str]]] = None,
        user_claims: Optional[Dict] = {}
    ) -> str:
        """
        Create token for access_token and refresh_token (utf-8)

        :param subject: Identifier for who this token is for example id or username from database.
        :param type_token: indicate token is access_token or refresh_token
        :param exp_time: Set the duration of the JWT
        :param fresh: Optional when token is access_token this param required
        :param algorithm: algorithm allowed to encode the token
        :param headers: valid dict for specifying additional headers in JWT header section
        :param issuer: expected issuer in the JWT
        :param audience: expected audience in the JWT
        :param user_claims: Custom claims to include in this token. This data must be dictionary

        :return: Encoded token
        """
        # Validation type data
        if not isinstance(subject, (str,int)):
            raise TypeError("subject must be a string or integer")
        if not isinstance(fresh, bool):
            raise TypeError("fresh must be a boolean")
        if audience and not isinstance(audience, (str, list, tuple, set, frozenset)):
            raise TypeError("audience must be a string or sequence")
        if algorithm and not isinstance(algorithm, str):
            raise TypeError("algorithm must be a string")
        if user_claims and not isinstance(user_claims, dict):
            raise TypeError("user_claims must be a dictionary")

        # Data section
        reserved_claims = {
            "sub": subject,
            "iat": self._get_int_from_datetime(datetime.now(timezone.utc)),
            "nbf": self._get_int_from_datetime(datetime.now(timezone.utc)),
            "jti": self._get_jwt_identifier()
        }

        custom_claims = {"type": type_token}

        # for access_token only fresh needed
        if type_token == 'access':
            custom_claims['fresh'] = fresh
        # if cookie in token location and csrf protection enabled
        if self.jwt_in_cookies and self._cookie_csrf_protect:
            custom_claims['csrf'] = self._get_jwt_identifier()

        if exp_time:
            reserved_claims['exp'] = exp_time
        if issuer:
            reserved_claims['iss'] = issuer
        if audience:
            reserved_claims['aud'] = audience

        algorithm = algorithm or self._algorithm

        try:
            secret_key = self._get_secret_key(algorithm,"encode")
        except Exception:
            raise

        return jwt.encode(
            {**reserved_claims, **custom_claims, **user_claims},
            secret_key,
            algorithm=algorithm,
            headers=headers
        ).decode('utf-8')

    def _has_token_in_denylist_callback(self) -> bool:
        """
        Return True if token denylist callback set
        """
        return self._token_in_denylist_callback is not None

    def _check_token_is_revoked(self, raw_token: Dict[str,Union[str,int,bool]]) -> None:
        """
        Ensure that AUTHJWT_DENYLIST_ENABLED is true and callback regulated, and then
        call function denylist callback with passing decode JWT, if true
        raise exception Token has been revoked
        """
        if not self._denylist_enabled:
            return

        if not self._has_token_in_denylist_callback():
            raise RuntimeError("A token_in_denylist_callback must be provided via "
                "the '@AuthJWT.token_in_denylist_loader' if "
                "authjwt_denylist_enabled is 'True'")

        if self._token_in_denylist_callback.__func__(raw_token):
            raise RevokedTokenError(status_code=401,message="Token has been revoked")

    def _get_expired_time(
        self,
        type_token: str,
        expires_time: Optional[Union[timedelta,int,bool]] = None
    ) -> Union[None,int]:
        """
        Dynamic token expired, if expires_time is False exp claim not created

        :param type_token: indicate token is access_token or refresh_token
        :param expires_time: duration expired jwt

        :return: duration exp claim jwt
        """
        if expires_time and not isinstance(expires_time, (timedelta,int,bool)):
            raise TypeError("expires_time must be between timedelta, int, bool")

        if expires_time is not False:
            if type_token == 'access':
                expires_time = expires_time or self._access_token_expires
            if type_token == 'refresh':
                expires_time = expires_time or self._refresh_token_expires

        if expires_time is not False:
            if isinstance(expires_time, bool):
                if type_token == 'access':
                    expires_time = self._access_token_expires
                if type_token == 'refresh':
                    expires_time = self._refresh_token_expires
            if isinstance(expires_time, timedelta):
                expires_time = int(expires_time.total_seconds())

            return self._get_int_from_datetime(datetime.now(timezone.utc)) + expires_time
        else:
            return None

    def create_access_token(
        self,
        subject: Union[str,int],
        fresh: Optional[bool] = False,
        algorithm: Optional[str] = None,
        headers: Optional[Dict] = None,
        expires_time: Optional[Union[timedelta,int,bool]] = None,
        audience: Optional[Union[str,Sequence[str]]] = None,
        user_claims: Optional[Dict] = {}
    ) -> str:
        """
        Create a access token with 15 minutes for expired time (default),
        info for param and return check to function create token

        :return: hash token
        """
        return self._create_token(
            subject=subject,
            type_token="access",
            exp_time=self._get_expired_time("access",expires_time),
            fresh=fresh,
            algorithm=algorithm,
            headers=headers,
            audience=audience,
            user_claims=user_claims,
            issuer=self._encode_issuer
        )

    def create_refresh_token(
        self,
        subject: Union[str,int],
        algorithm: Optional[str] = None,
        headers: Optional[Dict] = None,
        expires_time: Optional[Union[timedelta,int,bool]] = None,
        audience: Optional[Union[str,Sequence[str]]] = None,
        user_claims: Optional[Dict] = {}
    ) -> str:
        """
        Create a refresh token with 30 days for expired time (default),
        info for param and return check to function create token

        :return: hash token
        """
        return self._create_token(
            subject=subject,
            type_token="refresh",
            exp_time=self._get_expired_time("refresh",expires_time),
            algorithm=algorithm,
            headers=headers,
            audience=audience,
            user_claims=user_claims
        )

    def _get_csrf_token(self,encoded_token: str) -> str:
        """
        Returns the CSRF double submit token from an encoded JWT.

        :param encoded_token: The encoded JWT
        :return: The CSRF double submit token
        """
        return self._verified_token(encoded_token)['csrf']

    def set_access_cookies(
        self,
        encoded_access_token: str,
        response: Optional[Response] = None,
        max_age: Optional[int] = None
    ) -> None:
        """
        Configures the response to set access token in a cookie.
        this will also set the CSRF double submit values in a separate cookie

        :param encoded_access_token: The encoded access token to set in the cookies
        :param response: The FastAPI response object to set the access cookies in
        :param max_age: The max age of the cookie value should be the number of seconds (integer)
        """
        if not self.jwt_in_cookies:
            raise RuntimeWarning(
                "set_access_cookies() called without 'authjwt_token_location' configured to use cookies"
            )

        if max_age and not isinstance(max_age,int):
            raise TypeError("max_age must be a integer")
        if response and not isinstance(response,Response):
            raise TypeError("The response must be an object response FastAPI")

        response = response or self._response

        # Set the access JWT in the cookie
        response.set_cookie(
            self._access_cookie_key,
            encoded_access_token,
            max_age=max_age or self._cookie_max_age,
            path=self._access_cookie_path,
            domain=self._cookie_domain,
            secure=self._cookie_secure,
            httponly=True,
            samesite=self._cookie_samesite
        )

        # If enabled, set the csrf double submit access cookie
        if self._cookie_csrf_protect:
            response.set_cookie(
                self._access_csrf_cookie_key,
                self._get_csrf_token(encoded_access_token),
                max_age=max_age or self._cookie_max_age,
                path=self._access_csrf_cookie_path,
                domain=self._cookie_domain,
                secure=self._cookie_secure,
                httponly=False,
                samesite=self._cookie_samesite
            )

    def set_refresh_cookies(
        self,
        encoded_refresh_token: str,
        response: Optional[Response] = None,
        max_age: Optional[int] = None
    ) -> None:
        """
        Configures the response to set refresh token in a cookie.
        this will also set the CSRF double submit values in a separate cookie

        :param encoded_refresh_token: The encoded refresh token to set in the cookies
        :param response: The FastAPI response object to set the refresh cookies in
        :param max_age: The max age of the cookie value should be the number of seconds (integer)
        """
        if not self.jwt_in_cookies:
            raise RuntimeWarning(
                "set_refresh_cookies() called without 'authjwt_token_location' configured to use cookies"
            )

        if max_age and not isinstance(max_age,int):
            raise TypeError("max_age must be a integer")
        if response and not isinstance(response,Response):
            raise TypeError("The response must be an object response FastAPI")

        response = response or self._response

        # Set the refresh JWT in the cookie
        response.set_cookie(
            self._refresh_cookie_key,
            encoded_refresh_token,
            max_age=max_age or self._cookie_max_age,
            path=self._refresh_cookie_path,
            domain=self._cookie_domain,
            secure=self._cookie_secure,
            httponly=True,
            samesite=self._cookie_samesite
        )

        # If enabled, set the csrf double submit refresh cookie
        if self._cookie_csrf_protect:
            response.set_cookie(
                self._refresh_csrf_cookie_key,
                self._get_csrf_token(encoded_refresh_token),
                max_age=max_age or self._cookie_max_age,
                path=self._refresh_csrf_cookie_path,
                domain=self._cookie_domain,
                secure=self._cookie_secure,
                httponly=False,
                samesite=self._cookie_samesite
            )

    def unset_jwt_cookies(self,response: Optional[Response] = None) -> None:
        """
        Unset (delete) all jwt stored in a cookie

        :param response: The FastAPI response object to delete the JWT cookies in.
        """
        self.unset_access_cookies(response)
        self.unset_refresh_cookies(response)

    def unset_access_cookies(self,response: Optional[Response] = None) -> None:
        """
        Remove access token and access CSRF double submit from the response cookies

        :param response: The FastAPI response object to delete the access cookies in.
        """
        if not self.jwt_in_cookies:
            raise RuntimeWarning(
                "unset_access_cookies() called without 'authjwt_token_location' configured to use cookies"
            )

        if response and not isinstance(response,Response):
            raise TypeError("The response must be an object response FastAPI")

        response = response or self._response

        response.delete_cookie(
            self._access_cookie_key,
            path=self._access_cookie_path,
            domain=self._cookie_domain
        )

        if self._cookie_csrf_protect:
            response.delete_cookie(
                self._access_csrf_cookie_key,
                path=self._access_csrf_cookie_path,
                domain=self._cookie_domain
            )

    def unset_refresh_cookies(self,response: Optional[Response] = None) -> None:
        """
        Remove refresh token and refresh CSRF double submit from the response cookies

        :param response: The FastAPI response object to delete the refresh cookies in.
        """
        if not self.jwt_in_cookies:
            raise RuntimeWarning(
                "unset_refresh_cookies() called without 'authjwt_token_location' configured to use cookies"
            )

        if response and not isinstance(response,Response):
            raise TypeError("The response must be an object response FastAPI")

        response = response or self._response

        response.delete_cookie(
            self._refresh_cookie_key,
            path=self._refresh_cookie_path,
            domain=self._cookie_domain
        )

        if self._cookie_csrf_protect:
            response.delete_cookie(
                self._refresh_csrf_cookie_key,
                path=self._refresh_csrf_cookie_path,
                domain=self._cookie_domain
            )

    def _verify_and_get_jwt_optional_in_cookies(
        self,
        request: Union[Request,WebSocket],
        csrf_token: Optional[str] = None,
    ) -> "AuthJWT":
        """
        Optionally check if cookies have a valid access token. if an access token present in
        cookies, self._token will set. raises exception error when an access token is invalid
        or doesn't match with CSRF token double submit

        :param request: for identity get cookies from HTTP or WebSocket
        :param csrf_token: the CSRF double submit token
        """
        if not isinstance(request,(Request,WebSocket)):
            raise TypeError("request must be an instance of 'Request' or 'WebSocket'")

        cookie_key = self._access_cookie_key
        cookie = request.cookies.get(cookie_key)
        if not isinstance(request, WebSocket):
            csrf_token = request.headers.get(self._access_csrf_header_name)

        if cookie and self._cookie_csrf_protect and not csrf_token:
            if isinstance(request, WebSocket) or request.method in self._csrf_methods:
                raise CSRFError(status_code=401,message="Missing CSRF Token")

        # set token from cookie and verify jwt
        self._token = cookie
        self._verify_jwt_optional_in_request(self._token)

        decoded_token = self.get_raw_jwt()

        if decoded_token and self._cookie_csrf_protect and csrf_token:
            if isinstance(request, WebSocket) or request.method in self._csrf_methods:
                if 'csrf' not in decoded_token:
                    raise JWTDecodeError(status_code=422,message="Missing claim: csrf")
                if not hmac.compare_digest(csrf_token,decoded_token['csrf']):
                    raise CSRFError(status_code=401,message="CSRF double submit tokens do not match")

    def _verify_and_get_jwt_in_cookies(
        self,
        type_token: str,
        request: Union[Request,WebSocket],
        csrf_token: Optional[str] = None,
        fresh: Optional[bool] = False,
    ) -> "AuthJWT":
        """
        Check if cookies have a valid access or refresh token. if an token present in
        cookies, self._token will set. raises exception error when an access or refresh token
        is invalid or doesn't match with CSRF token double submit

        :param type_token: indicate token is access or refresh token
        :param request: for identity get cookies from HTTP or WebSocket
        :param csrf_token: the CSRF double submit token
        :param fresh: check freshness token if True
        """
        if type_token not in ['access','refresh']:
            raise ValueError("type_token must be between 'access' or 'refresh'")
        if not isinstance(request,(Request,WebSocket)):
            raise TypeError("request must be an instance of 'Request' or 'WebSocket'")

        if type_token == 'access':
            cookie_key = self._access_cookie_key
            cookie = request.cookies.get(cookie_key)
            if not isinstance(request, WebSocket):
                csrf_token = request.headers.get(self._access_csrf_header_name)
        if type_token == 'refresh':
            cookie_key = self._refresh_cookie_key
            cookie = request.cookies.get(cookie_key)
            if not isinstance(request, WebSocket):
                csrf_token = request.headers.get(self._refresh_csrf_header_name)

        if not cookie:
            raise MissingTokenError(status_code=401,message="Missing cookie {}".format(cookie_key))

        if self._cookie_csrf_protect and not csrf_token:
            if isinstance(request, WebSocket) or request.method in self._csrf_methods:
                raise CSRFError(status_code=401,message="Missing CSRF Token")

        # set token from cookie and verify jwt
        self._token = cookie
        self._verify_jwt_in_request(self._token,type_token,'cookies',fresh)

        decoded_token = self.get_raw_jwt()

        if self._cookie_csrf_protect and csrf_token:
            if isinstance(request, WebSocket) or request.method in self._csrf_methods:
                if 'csrf' not in decoded_token:
                    raise JWTDecodeError(status_code=422,message="Missing claim: csrf")
                if not hmac.compare_digest(csrf_token,decoded_token['csrf']):
                    raise CSRFError(status_code=401,message="CSRF double submit tokens do not match")

    def _verify_jwt_optional_in_request(self,token: str) -> None:
        """
        Optionally check if this request has a valid access token

        :param token: The encoded JWT
        """
        if token: self._verifying_token(token)

        if token and self.get_raw_jwt(token)['type'] != 'access':
            raise AccessTokenRequired(status_code=422,message="Only access tokens are allowed")

    def _verify_jwt_in_request(
        self,
        token: str,
        type_token: str,
        token_from: str,
        fresh: Optional[bool] = False
    ) -> None:
        """
        Ensure that the requester has a valid token. this also check the freshness of the access token

        :param token: The encoded JWT
        :param type_token: indicate token is access or refresh token
        :param token_from: indicate token from headers cookies, websocket
        :param fresh: check freshness token if True
        """
        if type_token not in ['access','refresh']:
            raise ValueError("type_token must be between 'access' or 'refresh'")
        if token_from not in ['headers','cookies','websocket']:
            raise ValueError("token_from must be between 'headers', 'cookies', 'websocket'")

        if not token:
            if token_from == 'headers':
                raise MissingTokenError(status_code=401,message="Missing {} Header".format(self._header_name))
            if token_from == 'websocket':
                raise MissingTokenError(status_code=1008,message="Missing {} token from Query or Path".format(type_token))

        # verify jwt
        issuer = self._decode_issuer if type_token == 'access' else None
        self._verifying_token(token,issuer)

        if self.get_raw_jwt(token)['type'] != type_token:
            msg = "Only {} tokens are allowed".format(type_token)
            if type_token == 'access':
                raise AccessTokenRequired(status_code=422,message=msg)
            if type_token == 'refresh':
                raise RefreshTokenRequired(status_code=422,message=msg)

        if fresh and not self.get_raw_jwt(token)['fresh']:
            raise FreshTokenRequired(status_code=401,message="Fresh token required")

    def _verifying_token(self,encoded_token: str, issuer: Optional[str] = None) -> None:
        """
        Verified token and check if token is revoked

        :param encoded_token: token hash
        :param issuer: expected issuer in the JWT
        """
        raw_token = self._verified_token(encoded_token,issuer)
        if raw_token['type'] in self._denylist_token_checks:
            self._check_token_is_revoked(raw_token)

    def _verified_token(self,encoded_token: str, issuer: Optional[str] = None) -> Dict[str,Union[str,int,bool]]:
        """
        Verified token and catch all error from jwt package and return decode token

        :param encoded_token: token hash
        :param issuer: expected issuer in the JWT

        :return: raw data from the hash token in the form of a dictionary
        """
        algorithms = self._decode_algorithms or [self._algorithm]

        try:
            unverified_headers = self.get_unverified_jwt_headers(encoded_token)
        except Exception as err:
            raise InvalidHeaderError(status_code=422,message=str(err))

        try:
            secret_key = self._get_secret_key(unverified_headers['alg'],"decode")
        except Exception:
            raise

        try:
            return jwt.decode(
                encoded_token,
                secret_key,
                issuer=issuer,
                audience=self._decode_audience,
                leeway=self._decode_leeway,
                algorithms=algorithms
            )
        except Exception as err:
            raise JWTDecodeError(status_code=422,message=str(err))

    def jwt_required(
        self,
        auth_from: str = "request",
        token: Optional[str] = None,
        websocket: Optional[WebSocket] = None,
        csrf_token: Optional[str] = None,
    ) -> None:
        """
        Only access token can access this function

        :param auth_from: for identity get token from HTTP or WebSocket
        :param token: the encoded JWT, it's required if the protected endpoint use WebSocket to
                      authorization and get token from Query Url or Path
        :param websocket: an instance of WebSocket, it's required if protected endpoint use a cookie to authorization
        :param csrf_token: the CSRF double submit token. since WebSocket cannot add specifying additional headers
                           its must be passing csrf_token manually and can achieve by Query Url or Path
        """
        if auth_from == "websocket":
            if websocket: self._verify_and_get_jwt_in_cookies('access',websocket,csrf_token)
            else: self._verify_jwt_in_request(token,'access','websocket')

        if auth_from == "request":
            if len(self._token_location) == 2:
                if self._token and self.jwt_in_headers:
                    self._verify_jwt_in_request(self._token,'access','headers')
                if not self._token and self.jwt_in_cookies:
                    self._verify_and_get_jwt_in_cookies('access',self._request)
            else:
                if self.jwt_in_headers:
                    self._verify_jwt_in_request(self._token,'access','headers')
                if self.jwt_in_cookies:
                    self._verify_and_get_jwt_in_cookies('access',self._request)

    def jwt_optional(
        self,
        auth_from: str = "request",
        token: Optional[str] = None,
        websocket: Optional[WebSocket] = None,
        csrf_token: Optional[str] = None,
    ) -> None:
        """
        If an access token in present in the request you can get data from get_raw_jwt() or get_jwt_subject(),
        If no access token is present in the request, this endpoint will still be called, but
        get_raw_jwt() or get_jwt_subject() will return None

        :param auth_from: for identity get token from HTTP or WebSocket
        :param token: the encoded JWT, it's required if the protected endpoint use WebSocket to
                      authorization and get token from Query Url or Path
        :param websocket: an instance of WebSocket, it's required if protected endpoint use a cookie to authorization
        :param csrf_token: the CSRF double submit token. since WebSocket cannot add specifying additional headers
                           its must be passing csrf_token manually and can achieve by Query Url or Path
        """
        if auth_from == "websocket":
            if websocket: self._verify_and_get_jwt_optional_in_cookies(websocket,csrf_token)
            else: self._verify_jwt_optional_in_request(token)

        if auth_from == "request":
            if len(self._token_location) == 2:
                if self._token and self.jwt_in_headers:
                    self._verify_jwt_optional_in_request(self._token)
                if not self._token and self.jwt_in_cookies:
                    self._verify_and_get_jwt_optional_in_cookies(self._request)
            else:
                if self.jwt_in_headers:
                    self._verify_jwt_optional_in_request(self._token)
                if self.jwt_in_cookies:
                    self._verify_and_get_jwt_optional_in_cookies(self._request)

    def jwt_refresh_token_required(
        self,
        auth_from: str = "request",
        token: Optional[str] = None,
        websocket: Optional[WebSocket] = None,
        csrf_token: Optional[str] = None,
    ) -> None:
        """
        This function will ensure that the requester has a valid refresh token

        :param auth_from: for identity get token from HTTP or WebSocket
        :param token: the encoded JWT, it's required if the protected endpoint use WebSocket to
                      authorization and get token from Query Url or Path
        :param websocket: an instance of WebSocket, it's required if protected endpoint use a cookie to authorization
        :param csrf_token: the CSRF double submit token. since WebSocket cannot add specifying additional headers
                           its must be passing csrf_token manually and can achieve by Query Url or Path
        """
        if auth_from == "websocket":
            if websocket: self._verify_and_get_jwt_in_cookies('refresh',websocket,csrf_token)
            else: self._verify_jwt_in_request(token,'refresh','websocket')

        if auth_from == "request":
            if len(self._token_location) == 2:
                if self._token and self.jwt_in_headers:
                    self._verify_jwt_in_request(self._token,'refresh','headers')
                if not self._token and self.jwt_in_cookies:
                    self._verify_and_get_jwt_in_cookies('refresh',self._request)
            else:
                if self.jwt_in_headers:
                    self._verify_jwt_in_request(self._token,'refresh','headers')
                if self.jwt_in_cookies:
                    self._verify_and_get_jwt_in_cookies('refresh',self._request)

    def fresh_jwt_required(
        self,
        auth_from: str = "request",
        token: Optional[str] = None,
        websocket: Optional[WebSocket] = None,
        csrf_token: Optional[str] = None,
    ) -> None:
        """
        This function will ensure that the requester has a valid access token and fresh token

        :param auth_from: for identity get token from HTTP or WebSocket
        :param token: the encoded JWT, it's required if the protected endpoint use WebSocket to
                      authorization and get token from Query Url or Path
        :param websocket: an instance of WebSocket, it's required if protected endpoint use a cookie to authorization
        :param csrf_token: the CSRF double submit token. since WebSocket cannot add specifying additional headers
                           its must be passing csrf_token manually and can achieve by Query Url or Path
        """
        if auth_from == "websocket":
            if websocket: self._verify_and_get_jwt_in_cookies('access',websocket,csrf_token,True)
            else: self._verify_jwt_in_request(token,'access','websocket',True)

        if auth_from == "request":
            if len(self._token_location) == 2:
                if self._token and self.jwt_in_headers:
                    self._verify_jwt_in_request(self._token,'access','headers',True)
                if not self._token and self.jwt_in_cookies:
                    self._verify_and_get_jwt_in_cookies('access',self._request,fresh=True)
            else:
                if self.jwt_in_headers:
                    self._verify_jwt_in_request(self._token,'access','headers',True)
                if self.jwt_in_cookies:
                    self._verify_and_get_jwt_in_cookies('access',self._request,fresh=True)

    def get_raw_jwt(self,encoded_token: Optional[str] = None) -> Optional[Dict[str,Union[str,int,bool]]]:
        """
        this will return the python dictionary which has all of the claims of the JWT that is accessing the endpoint.
        If no JWT is currently present, return None instead

        :param encoded_token: The encoded JWT from parameter
        :return: claims of JWT
        """
        token = encoded_token or self._token

        if token:
            return self._verified_token(token)
        return None

    def get_jti(self,encoded_token: str) -> str:
        """
        Returns the JTI (unique identifier) of an encoded JWT

        :param encoded_token: The encoded JWT from parameter
        :return: string of JTI
        """
        return self._verified_token(encoded_token)['jti']

    def get_jwt_subject(self) -> Optional[Union[str,int]]:
        """
        this will return the subject of the JWT that is accessing this endpoint.
        If no JWT is present, `None` is returned instead.

        :return: sub of JWT
        """
        if self._token:
            return self._verified_token(self._token)['sub']
        return None

    def get_unverified_jwt_headers(self,encoded_token: Optional[str] = None) -> dict:
        """
        Returns the Headers of an encoded JWT without verifying the actual signature of JWT

        :param encoded_token: The encoded JWT to get the Header from
        :return: JWT header parameters as a dictionary
        """
        encoded_token = encoded_token or self._token

        return jwt.get_unverified_header(encoded_token)
