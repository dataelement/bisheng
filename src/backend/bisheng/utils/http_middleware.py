# Define a custom middleware class
from time import time

from fastapi import Request
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from bisheng.core.logger import trace_id_generator, trace_id_var
from bisheng.utils import get_request_ip


class CustomMiddleware(BaseHTTPMiddleware):
    """切面程序"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        # You can modify the request before passing it to the next middleware or endpoint
        if request.headers.get('x-trace-id'):
            trace_id = request.headers.get('x-trace-id')
        else:
            trace_id = trace_id_generator()
        # 有Nginx  二选一 得看NGINX 的配置
        ip = get_request_ip(request)
        path = request.url
        trace_id_var.set(trace_id)

        logger.info(f"| {ip} | {path}")
        start_time = time()
        response = await call_next(request)
        process_time = round(time() - start_time, 4)
        response.headers["X-Process-Time"] = str(process_time)
        response.headers["X-Trace-ID"] = trace_id
        logger.info(f"| {ip} | {path}：process_time={process_time}s")
        return response
