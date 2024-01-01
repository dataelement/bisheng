import logging
from pathlib import Path
from time import time
from typing import Optional
from uuid import uuid4

import orjson
from loguru import logger
from rich.logging import RichHandler
from starlette.middleware.base import BaseHTTPMiddleware

VALID_LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']


def serialize(record):
    subset = {
        'timestamp': record['time'].timestamp(),
        'message': record['message'],
        'level': record['level'].name,
        'module': record['module'],
    }
    return orjson.dumps(subset)


def patching(record):
    # Ensure that 'extra' exists in the record.
    record['extra']['serialized'] = serialize(record)


def configure(log_level: Optional[str] = None, log_file: Optional[Path] = None):
    if log_level is None:
        log_level = 'INFO'
    # Human-readable
    log_format = '<level>[{thread.name} {name}:{line}]</level> - <level>trace={extra[trace_id]} {message}</level>'

    # log_format = log_format_dev if log_level.upper() == "DEBUG" else log_format_prod
    logger.remove()  # Remove default handlers
    logger.patch(patching)
    # Configure loguru to use RichHandler
    logger.configure(handlers=[{
        'sink':
        RichHandler(rich_tracebacks=True,
                    markup=True,
                    log_time_format='[%Y-%m-%d %H:%M:%S.%f]',
                    tracebacks_width=1000),
        'format':
        log_format,
        'level':
        log_level.upper(),
    }],
                     extra={'trace_id': '1'})

    if not log_file:
        log_file = 'data/bisheng.log'

    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger.add(
        sink=str(log_file),
        level=log_level.upper(),
        format=log_format,
        rotation='00:00',  # Log rotation based on file size
        retention='3 days',
        serialize=True,
    )

    logger.debug(f'Logger set up with log level: {log_level}')
    if log_file:
        logger.debug(f'Log file: {log_file}')


# Define a custom middleware class
class CustomMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request, call_next):
        # You can modify the request before passing it to the next middleware or endpoint
        trace_id = str(uuid4().hex)
        start_time = time()
        with logger.contextualize(trace_id=trace_id):
            response = await call_next(request)
            process_time = round(time() - start_time, 2)

        logger.info(
            f'traceId={trace_id} {request.url.path} {response.status_code} timecost={process_time}'
        )

        return response


class InterceptHandler(logging.Handler):

    def emit(self, record):
        # 获取对应的 Loguru 级别
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        # 将 logging 记录转发到 loguru
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


# 将标准库的日志记录发送到上面定义的处理程序
log_level_value = getattr(logging, 'DEBUG', logging.INFO)
logging.basicConfig(handlers=[InterceptHandler()], level=log_level_value)

# # 设置所有导入模块的日志级别
# for name in list(sys.modules.keys()):
#     logging.getLogger(name).setLevel(logging.DEBUG)
