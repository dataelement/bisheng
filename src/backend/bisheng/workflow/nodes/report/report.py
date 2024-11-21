import io
from uuid import uuid4

from bisheng.utils.minio_client import MinioClient
from bisheng.workflow.callback.event import OutputMsgData
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.report.template import DocxTemplateRender


class ReportNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._report_info = self.node_params['report_info']
        self._object_name = f"workflow/report/{self._report_info['version_key']}.docx"
        self._file_name = self._report_info['file_name'] if self._report_info['file_name'] else 'tmp_report.docx'
        if not self._file_name.endswith('.docx'):
            self._file_name += '.docx'
        self._minio_client = MinioClient()

    def _run(self, unique_id: str):
        # 下载报告模板文件
        file_content = self._minio_client.get_object(self._minio_client.bucket, self._object_name)
        doc_parse = DocxTemplateRender(file_content=io.BytesIO(file_content))
        # 获取所有的节点变量
        all_variables = self.graph_state.get_all_variables()
        template_def = []
        for key, value in all_variables.items():
            template_def.append(["{{" + key + "}}", value])

        # 将变量渲染到docx模板文件
        output_doc = doc_parse.render(template_def)
        output_content = io.BytesIO()
        output_doc.save(output_content)
        output_content.seek(0)

        # minio的临时目录
        tmp_object_name = f"workflow/report/{uuid4().hex}/{self._file_name}"
        # upload file to minio
        self._minio_client.upload_tmp(tmp_object_name, output_content.read())
        # get share link
        file_share_url = self._minio_client.get_share_link(tmp_object_name, self._minio_client.tmp_bucket)

        self.callback_manager.on_output_msg(OutputMsgData(**{
            'unique_id': unique_id,
            'node_id': self.id,
            'msg': "",
            'files': [{'path': file_share_url, 'name': self._file_name}],
            'output_key': '',
            'stream': False
        }))
