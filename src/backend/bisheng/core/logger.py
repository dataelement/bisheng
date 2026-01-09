import logging
import sys
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

from loguru import logger

from bisheng.core.config.settings import LoggerConf

trace_id_var: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)


def trace_id_generator() -> str:
    return str(uuid.uuid4().hex)


class TraceIdFilter:
    def __init__(self, filter_func=None):
        self.filter_func = filter_func

    def __call__(self, record):
        if record["extra"].get("trace_id") is None:
            record["extra"]["trace_id"] = trace_id_var.get()
        if self.filter_func is not None:
            return self.filter_func(record)
        return True


class InterceptHandler(logging.Handler):
    """Interception Criteria logging logs, transferring to Loguru <g id="Bold">Medical Treatment:</g>"""

    def emit(self, record):
        # Dapatkan loguru counterpart&apos;s level
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Get call stack depth
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        # Forward to loguru
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def set_logger_config(logger_config: LoggerConf):
    """
    Configuration Logs
    :param logger_config:
    :return:
    """
    logger.remove()

    # Configure Root Logger
    logging.root.handlers = [InterceptHandler()]
    logging.root.setLevel(logger_config.level)

    # Block all existing loggers
    for name in logging.root.manager.loggerDict.keys():
        logging_logger = logging.getLogger(name)
        logging_logger.handlers = [InterceptHandler()]
        logging_logger.propagate = False

    # Add Default Console Log Processor
    logger.add(
        sys.stdout,
        format=logger_config.format,
        level=logger_config.level,
        filter=TraceIdFilter(),
        enqueue=True,
        backtrace=True,
        diagnose=False
    )

    # Add additional log processors
    for handler in logger_config.handlers:
        log_file = Path(handler['sink'])
        log_file.parent.mkdir(parents=True, exist_ok=True)
        filter_func = handler.pop('filter', None)
        logger.add(**handler, filter=TraceIdFilter(filter_func))

    logger.debug(f'Logger set up with log level: {logger_config.level}')
