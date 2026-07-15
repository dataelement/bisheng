import re
from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any

from loguru import logger
from minio import Minio

# Deliverables must be written to the RELATIVE ``output/`` (or intermediate
# ``scratch/``) directory under the executor's working dir — that dir is the only
# location harvested back into the linsight workspace. A leading-slash
# ``/output/...`` lands at the container filesystem root, OUTSIDE the harvested
# working dir (and, for the shared LocalExecutor, cannot be safely rescued from
# there without leaking one task's files into another). Such a write therefore
# vanishes silently from the result panel. This regex flags the pattern in
# submitted code (string literal starting with ``/output`` or ``/scratch``) so the
# executor can append a corrective notice and the model self-corrects next step.
_ABSOLUTE_DELIVERABLE_RE = re.compile(r"""['"]/(?:output|scratch)(?:/|['"])""")

ABSOLUTE_PATH_NOTICE = (
    "\n\n[SYSTEM NOTICE] Your code wrote file(s) to an ABSOLUTE path "
    "(/output/... or /scratch/...). Files written outside the current working "
    "directory are DISCARDED and were NOT delivered to the user. Re-run and write "
    "to the RELATIVE path with no leading slash, e.g. `output/report.pdf` for "
    "deliverables or `scratch/temp.png` for intermediate files."
)


class BaseExecutor(ABC):
    def __init__(self, minio: dict, **kwargs):
        self.minio = minio
        # 将代码生成的文件同步到本地的路径
        self.local_sync_path = kwargs.get("local_sync_path", None)

    @abstractmethod
    def run(self, code: str) -> Any:
        raise NotImplementedError()

    @staticmethod
    def absolute_path_advisory(code: str) -> str:
        """Corrective notice to append when ``code`` writes to an absolute
        ``/output``/``/scratch`` path (which escapes the harvested working dir and
        makes the deliverable silently vanish); empty string otherwise.

        String-literal match only (leading-slash ``/output`` / ``/scratch``), which
        is specific enough that false positives are negligible, and the notice is
        non-blocking (appended to the tool result, never rejects the run).
        """
        if code and _ABSOLUTE_DELIVERABLE_RE.search(code):
            return ABSOLUTE_PATH_NOTICE
        return ""

    def upload_minio(
        self,
        object_name: str,
        file_path,
    ) -> str:
        # 初始化minio
        if not self.minio:
            return ""

        minio_client = Minio(
            endpoint=self.minio.get("endpoint"),
            access_key=self.minio.get("access_key"),
            secret_key=self.minio.get("secret_key"),
            secure=self.minio.get("schema") or self.minio.get("secure"),
            cert_check=self.minio.get("cert_check"),
        )
        minio_share = Minio(
            endpoint=self.minio.get("sharepoint"),
            access_key=self.minio.get("access_key"),
            secret_key=self.minio.get("secret_key"),
            secure=self.minio.get("share_schema", False),
            cert_check=self.minio.get("share_cert_check", False),
        )
        bucket = self.minio.get("tmp_bucket", "tmp-dir")
        logger.debug(
            "upload_file obj={} bucket={} file_path={}",
            object_name,
            bucket,
            file_path,
        )
        minio_client.fput_object(
            bucket_name=bucket,
            object_name=object_name,
            file_path=file_path,
        )
        return minio_share.presigned_get_object(
            bucket_name=bucket,
            object_name=object_name,
            expires=timedelta(days=7),
        )

    def close(self) -> None:
        pass
