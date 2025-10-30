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
    def __call__(self, record):
        record["extra"]["trace_id"] = trace_id_var.get()
        return True


class InterceptHandler(logging.Handler):
    """拦截标准 logging 日志，转交给 Loguru 处理"""

    def emit(self, record):
        # 获取 loguru 对应的 level
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 获取调用堆栈深度
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        # 转发到 loguru
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def set_logger_config(logger_config: LoggerConf):
    """
    配置日志
    :param logger_config:
    :return:
    """
    logger.remove()

    # 配置根日志记录器
    logging.root.handlers = [InterceptHandler()]
    logging.root.setLevel(logger_config.level)

    # 拦截所有已存在的日志记录器
    for name in logging.root.manager.loggerDict.keys():
        logging_logger = logging.getLogger(name)
        logging_logger.handlers = [InterceptHandler()]
        logging_logger.propagate = False

    # 添加默认控制台日志处理器
    logger.add(
        sys.stdout,
        format=logger_config.format,
        level=logger_config.level,
        filter=TraceIdFilter(),
        enqueue=True,
        backtrace=True,
        diagnose=False
    )

    # 添加额外的日志处理器
    for handler in logger_config.handlers:
        log_file = Path(handler['sink'])
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logger.add(**handler, filter=TraceIdFilter())

    logger.debug(f'Logger set up with log level: {logger_config.level}')
