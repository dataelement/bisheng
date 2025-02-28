import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Optional

from langchain_core.pydantic_v1 import BaseModel, Field, root_validator

from bisheng_langchain.gpts.tools.api_tools.base import (APIToolBase,
                                                         MultArgsSchemaTool)


class InputArgs(BaseModel):
    receiver: str = Field(description="收件人）")
    subject: str = Field(description="邮件主题")
    content: str = Field(description="邮件正文内容")


class EmailMessageTool(APIToolBase):

    email_account: str = Field(description="发件人邮箱")
    email_password: str = Field(description="邮箱授权码/密码")
    smtp_server: str = Field(description="SMTP服务器地址")
    encrypt_method: str = Field(description="encrypt_method")
    smtp_port: int = Field(default=465, description=" 端口号（SSL一般465，TLS用587）")

    def send_email(
        self,
        receiver,
        subject,
        content,
    ):
        """
        发送电子邮件函数

        参数：
        sender : str - 发件人邮箱
        password : str - 邮箱授权码/密码
        receiver : str/list - 收件人（多个用逗号）
        subject : str - 邮件主题
        content : str - 邮件正文内容
        content_type : str - 内容类型（plain/html）
        attachments : list - 附件路径列表
        smtp_server : str - SMTP服务器地址
        port : int - 端口号（SSL一般465，TLS用587）
        """

        try:
            content_type = "plain"
            # 创建邮件对象
            msg = MIMEMultipart()
            msg["From"] = self.email_account
            msg["To"] = receiver
            msg["Subject"] = subject

            # 添加正文
            body = MIMEText(content, content_type, "utf-8")
            msg.attach(body)

            # 添加附件
            # if attachments:
            #     for file_path in attachments:
            #         with open(file_path, "rb") as f:
            #             part = MIMEApplication(f.read())
            #             part.add_header(
            #                 "Content-Disposition",
            #                 "attachment",
            #                 filename=os.path.basename(file_path),
            #             )
            #             msg.attach(part)

                # 创建SMTP连接
            if self.smtp_port == 465:
                # SSL连接
                server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
            else:
                # TLS连接
                server = smtplib.SMTP(self.smtp_server, self.smtp_port)
                server.starttls()

            # 登录邮箱
            server.login(self.email_account, self.email_password)

            # 发送邮件
            server.sendmail(self.email_account, receiver.split(","), msg.as_string())
        except Exception as e:
            raise Exception(f"邮件发送失败：{e}")

        return "发送成功"

    @classmethod
    def get_api_tool(cls, name: str, **kwargs: Any) -> "EmailMessageTool":
        attr_name = name.split("_", 1)[-1]
        c = EmailMessageTool(**kwargs)
        class_method = getattr(c, attr_name)

        return MultArgsSchemaTool(
            name=name,
            description=class_method.__doc__,
            func=class_method,
            args_schema=InputArgs,
        )
