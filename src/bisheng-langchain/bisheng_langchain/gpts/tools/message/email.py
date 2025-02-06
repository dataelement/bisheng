import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import os

from bisheng_langchain.gpts.tools.api_tools.base import APIToolBase

class EmailMessageTool(APIToolBase):

    @classmethod
    def send_email(cls,sender, password, receiver, subject, content, 
                content_type='plain', attachments=None, smtp_server='smtp.qq.com', port=465):
        """
        发送电子邮件函数
        
        参数：
        sender : str - 发件人邮箱
        password : str - 邮箱授权码/密码
        receiver : str/list - 收件人（多个用列表）
        subject : str - 邮件主题
        content : str - 邮件正文内容
        content_type : str - 内容类型（plain/html）
        attachments : list - 附件路径列表
        smtp_server : str - SMTP服务器地址
        port : int - 端口号（SSL一般465，TLS用587）
        """
        
        # 创建邮件对象
        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = ', '.join(receiver) if isinstance(receiver, list) else receiver
        msg['Subject'] = subject

        # 添加正文
        body = MIMEText(content, content_type, 'utf-8')
        msg.attach(body)

        # 添加附件
        if attachments:
            for file_path in attachments:
                with open(file_path, 'rb') as f:
                    part = MIMEApplication(f.read())
                    part.add_header('Content-Disposition', 'attachment', 
                                filename=os.path.basename(file_path))
                    msg.attach(part)

        try:
            # 创建SMTP连接
            if port == 465:
                # SSL连接
                server = smtplib.SMTP_SSL(smtp_server, port)
            else:
                # TLS连接
                server = smtplib.SMTP(smtp_server, port)
                server.starttls()
            
            # 登录邮箱
            server.login(sender, password)
            
            # 发送邮件
            server.sendmail(sender, receiver, msg.as_string())
            print("邮件发送成功！")
            
        except Exception as e:
            print(f"发送失败: {str(e)}")
        finally:
            server.quit()

    # -------------------- 使用示例 -------------------- 
    # if __name__ == "__main__":
    #     # 安全提示：建议将敏感信息存储在环境变量中
    #     # 例如 os.environ.get('EMAIL_PASSWORD')
    #     
    #     # 基础文本邮件
    #     send_email(
    #         sender='your_email@qq.com',
    #         password='your_authorization_code',  # 注意：QQ邮箱用授权码，非登录密码
    #         receiver=['target1@example.com', 'target2@example.com'],
    #         subject='测试文本邮件',
    #         content='这是一封来自Python的测试邮件',
    #         smtp_server='smtp.qq.com',
    #         port=465
    #     )
    #
    #     # HTML邮件+附件
    #     html_content = '''
    #     <h1 style="color:red">HTML内容测试</h1>
    #     <p>这是一封带样式的邮件</p>
    #     <ul>
    #         <li>项目1</li>
    #         <li>项目2</li>
    #     </ul>
    #     '''
    #     
    #     send_email(
    #         sender='your_email@163.com',
    #         password='your_password',
    #         receiver='target@example.com',
    #         subject='HTML邮件测试',
    #         content=html_content,
    #         content_type='html',
    #         attachments=['data.xlsx', 'report.pdf'],
    #         smtp_server='smtp.163.com',
    #         port=465
    #     )
