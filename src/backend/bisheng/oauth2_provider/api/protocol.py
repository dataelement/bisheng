"""OAuth wire errors stay local to public protocol routes, ahead of platform handlers."""

from json import JSONDecodeError

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from bisheng.common.errcode.base import BaseErrorCode

# Persisted business codes remain unchanged for admin/consent platform clients.
_PROTOCOL_ERRORS = {
    28101: ("invalid_request", 400),
    28102: ("invalid_client", 401),
    28103: ("invalid_client", 401),
    28104: ("invalid_client", 401),
    28105: ("invalid_request", 400),
    28106: ("invalid_scope", 400),
    28107: ("invalid_grant", 400),
    28108: ("invalid_grant", 400),
    28109: ("invalid_grant", 400),
    28112: ("invalid_token", 401),
    28113: ("invalid_grant", 400),
    28114: ("unsupported_grant_type", 400),
    28115: ("invalid_target", 400),
    28116: ("unauthorized_client", 400),
    28117: ("temporarily_unavailable", 503),
    28119: ("consent_required", 400),
}


class OAuth2ProtocolRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def protocol_handler(request):
            try:
                response = await handler(request)
            except BaseErrorCode as exc:
                mapped = _PROTOCOL_ERRORS.get(exc.code)
                if mapped is None:
                    raise
                error, status = mapped
                headers = {}
                if error == "invalid_client":
                    headers["WWW-Authenticate"] = 'Basic realm="oauth2"'
                elif error == "invalid_token":
                    headers["WWW-Authenticate"] = 'Bearer error="invalid_token"'
                response = JSONResponse(
                    status_code=status,
                    content={"error": error, "error_description": exc.message},
                    headers=headers,
                )
            except (RequestValidationError, JSONDecodeError):
                response = JSONResponse(status_code=400, content={"error": "invalid_request"})
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
            return response

        return protocol_handler
