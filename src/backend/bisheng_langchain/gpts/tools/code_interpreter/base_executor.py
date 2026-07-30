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

# Delivery zones of the executor working dir. ``output/`` is the ONLY zone the
# linsight harvester (``get_final_result_file``) treats as deliverables;
# ``scratch/`` is explicitly intermediate.
OUTPUT_DIR_NAME = "output"
SCRATCH_DIR_NAME = "scratch"

# A file created at the working-directory ROOT sits in no zone at all, so it was
# never delivered — the model just wrote ``report.xlsx`` instead of
# ``output/report.xlsx``. The tool description asks for ``output/`` but that is a
# soft contract the model regularly misses (and when it does, the deliverable
# silently disappears from the result panel). The executor therefore relocates
# such files itself and tells the model the new paths, because the old ones stop
# resolving after the move.
RELOCATED_PATH_NOTICE_HEADER = (
    "\n\n[SYSTEM NOTICE] The following file(s) were written to the working-directory "
    "ROOT, which is NOT a delivery zone — files there are never delivered to the user. "
    "They have been MOVED into `output/`. Use the NEW paths from now on; the old paths "
    "no longer exist. To avoid this, write deliverables to `output/` and intermediate "
    "files to `scratch/` directly.\n"
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

    @staticmethod
    def relocation_advisory(moved: list[tuple[str, str]]) -> str:
        """Corrective notice listing ``(old_rel, new_rel)`` relocations into
        ``output/``; empty string when nothing was moved.

        Paired with the relocation itself (not a substitute for it): the move is
        what makes the file deliverable, the notice is what keeps the model's
        follow-up reads from hitting a path that no longer exists.
        """
        if not moved:
            return ""
        lines = "\n".join(f"- {old} -> {new}" for old, new in moved)
        return RELOCATED_PATH_NOTICE_HEADER + lines

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
