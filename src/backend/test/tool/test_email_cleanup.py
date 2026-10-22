import smtplib

import pytest

from bisheng_langchain.gpts.tools.api_tools import EmailMessageTool


@pytest.mark.parametrize(
    "port,failure_stage,close_failure",
    [
        (465, None, False),
        (1025, None, False),
        (465, "login", False),
        (1025, "starttls", False),
        (1025, "sendmail", False),
        (465, "login", True),
    ],
)
def test_smtp_connection_has_timeout_and_closes_after_send(
    monkeypatch, port, failure_stage, close_failure
):
    connections = []

    class SMTPConnection:
        def __init__(self, host, smtp_port, **kwargs):
            self.timeout = kwargs.get("timeout")
            self.closed = False
            connections.append(self)

        def run_stage(self, stage):
            if failure_stage == stage:
                raise smtplib.SMTPException("smtp-failure")

        def starttls(self):
            self.run_stage("starttls")

        def login(self, *args):
            self.run_stage("login")

        def sendmail(self, *args):
            self.run_stage("sendmail")

        def close(self):
            self.closed = True
            if close_failure:
                raise OSError("cleanup-failure")

    monkeypatch.setattr(smtplib, "SMTP", SMTPConnection)
    monkeypatch.setattr(smtplib, "SMTP_SSL", SMTPConnection)
    tool = EmailMessageTool(
        email_account="sender@example.invalid",
        email_password="diagnostic",
        smtp_server="smtp.example.invalid",
        smtp_port=port,
        encrypt_method="SSL" if port == 465 else "TLS",
    )
    if failure_stage:
        with pytest.raises(Exception, match=r"邮件发送失败.*smtp-failure"):
            tool.send_email(receiver="receiver@example.invalid", subject="诊断", content="诊断")
    else:
        assert tool.send_email(
            receiver="receiver@example.invalid", subject="诊断", content="诊断"
        ) == "发送成功"

    assert connections[0].closed, "发送完成或失败后均须释放 SMTP 连接"
    assert connections[0].timeout == 30
