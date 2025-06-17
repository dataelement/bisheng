import socket
import time
import json
from bisheng.settings import settings, SYSLogConf

class RawSyslogClient:
    def __init__(self, config: SYSLogConf):
        self.host = config.host
        self.port = config.port
        self.prefix = config.name
        self.log_format = config.log_format
        self.date_format = config.date_format
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _format_message(self, level: str, message: str) -> str:
        # 简化 syslog PRI 计算 (level 映射到 syslog priority，通常使用 user facility：1 << 3 = 8)
        LEVELS = {
            'debug': 7,
            'info': 6,
            'warning': 4,
            'error': 3,
            'critical': 2
        }
        pri = 8 + LEVELS.get(level.lower(), 6)  # facility=1 (user), severity from LEVELS

        timestamp = time.strftime(self.date_format, time.localtime())
        hostname = socket.gethostname()
        return f"<{pri}>{timestamp} {hostname} {self.prefix}: {message}"

    def _send(self, level: str, message: str):
        payload = self._format_message(level, message)
        self.sock.sendto(payload.encode(), (self.host, self.port))

    def debug(self, message): self._send("debug", message)
    def info(self, message): self._send("info", message)
    def warning(self, message): self._send("warning", message)
    def error(self, message): self._send("error", message)
    def critical(self, message): self._send("critical", message)

    def log_message_session(self, message):
        self.info("MessageSession-" + json.dumps(message,ensure_ascii=False))

    def log_audit_log(self, message):
        self.info("AuditLog-" + json.dumps(message,ensure_ascii=False))

    def log_chat_message(self, message):
        self.info("ChatMessage-" + json.dumps(message,ensure_ascii=False))


syslog_client = RawSyslogClient(settings.syslog_conf)