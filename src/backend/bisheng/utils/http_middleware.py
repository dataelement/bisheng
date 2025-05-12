# Define a custom middleware class
from time import time
from uuid import uuid4

from fastapi import Request
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


class CustomMiddleware(BaseHTTPMiddleware):
    """切面程序"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        # You can modify the request before passing it to the next middleware or endpoint
        if request.headers.get('x-trace-id'):
            trace_id = request.headers.get('x-trace-id')
        else:
            trace_id = str(uuid4().hex)
        start_time = time()
        with logger.contextualize(trace_id=trace_id):
            logger.info(f'{request.method} {request.url.path}')
            response = await call_next(request)
            process_time = round((time() - start_time) * 1000, 3)
            logger.info(f'{request.method} {request.url.path} {response.status_code} timecost={process_time}')
            return response
