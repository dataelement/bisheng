import io
import tempfile
from uuid import uuid4

from loguru import logger

from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.utils import generate_uuid
from bisheng.workflow.callback.event import OutputMsgData
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.report.docx_replace import DocxReplacer
from bisheng.workflow.nodes.report.text_classification import TextClassificationReport


class ReportNode(BaseNode):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._report_info = self.node_params["report_info"]
        self._version_key = self._report_info["version_key"].split("_")[0]
        self._object_name = f"workflow/report/{self._version_key}.docx"
        self._file_name = self._report_info["file_name"] if self._report_info["file_name"] else "tmp_report.docx"
        if not self._file_name.endswith(".docx"):
            self._file_name += ".docx"
        self._minio_client = get_minio_storage_sync()

    def _run(self, unique_id: str):
        """Master Execution Process"""
        with tempfile.TemporaryDirectory() as temp_dir:
            logger.debug("=== Download report template ===")
            template_content = self._download_template()
            docx_replacer = DocxReplacer(io.BytesIO(template_content))
            template_variables = docx_replacer.extract_variables()
            if not template_variables:
                logger.debug("=== Report template not found variables ===")
                finally_document = template_content
            else:
                logger.debug("=== Report template found variables ===")
                # Get workflow variables
                logger.debug("=== Get workflow variables ===")
                workflow_variables = {}
                text_classification = TextClassificationReport(temp_dir)
                for one_variables in template_variables:
                    variable_value = self.get_other_node_variable(one_variables)
                    if type(variable_value) != str:
                        variable_value = str(variable_value)
                    variable_value = text_classification.get_all_classified_data(variable_value)
                    workflow_variables[one_variables] = variable_value
                logger.debug("=== replace report template variables ===")
                output_docx_path = f"{temp_dir}/{generate_uuid()}.docx"
                docx_replacer.replace_and_save(workflow_variables, output_docx_path)
                with open(output_docx_path, "rb") as f:
                    finally_document = f.read()

            # SAVE AND SHARE
            logger.info("=== Walking Tongs7: Save and share documents ===")
            share_url = self._save_and_share_document(finally_document)

            # Send Output Message
            self._send_output_message(unique_id, share_url)

            logger.info("=== Report Generation Complete ===")

    def _download_template(self) -> bytes:
        """Download sample"""
        if not self._minio_client.object_exists_sync(self._minio_client.bucket, self._object_name):
            raise Exception(f"Template file does not exists!: {self._object_name}")

        template_content = self._minio_client.get_object_sync(self._minio_client.bucket, self._object_name)
        logger.info(f"Template downloaded successfully, size: {len(template_content)} byte")

        return template_content

    def _save_and_share_document(self, document_content: bytes) -> str:
        """Save the document and get a share link"""
        # Generate unique file path
        tmp_object_name = f"workflow/report/{uuid4().hex}/{self._file_name}"

        # Uploaded toMinIO
        self._minio_client.put_object_tmp_sync(tmp_object_name, document_content)

        # Get share link
        share_url = self._minio_client.get_share_link_sync(tmp_object_name, self._minio_client.tmp_bucket)

        logger.info(f"Document saved successfully: {tmp_object_name}")
        logger.info(f"Share Links: {share_url}")

        return share_url

    def _send_output_message(self, unique_id: str, share_url: str):
        """Send Output Message"""
        self.callback_manager.on_output_msg(
            OutputMsgData(
                unique_id=unique_id,
                node_id=self.id,
                name=self.name,
                msg="",
                files=[{"path": share_url, "name": self._file_name}],
                output_key="",
            )
        )
