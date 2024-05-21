import logging
from pathlib import Path

import orjson
from loguru import logger
from rich.console import Console
from rich.logging import RichHandler

from bisheng.settings import LoggerConf

VALID_LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL', 'EXCEPTION']


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


def configure(logger_conf: LoggerConf):
    log_level = logger_conf.level

    # log_format = log_format_dev if log_level.upper() == "DEBUG" else log_format_prod
    logger.remove()  # Remove default handlers
    logger.patch(patching)
    # Configure loguru to use RichHandler

    logger.configure(handlers=[{
        'sink':
        RichHandler(console=Console(width=300),
                    markup=True,
                    log_time_format='[%Y-%m-%d %H:%M:%S.%f]',
                    show_path=False,
                    show_level=False),
        'format':
        logger_conf.format,
        'level':
        log_level.upper(),
    }],
                     extra={'trace_id': '1'})

    for one in logger_conf.handlers:
        log_file = Path(one['sink'])
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logger.add(**one)
        logger.debug(f'Logger set up with log handler: {one["sink"]}')

    logger.debug(f'Logger set up with log level: {log_level}')


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
