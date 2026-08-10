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

# The read-side twin. ``/skills`` and ``/uploads`` are zones the model READS: the
# workspace tools hand it ``/skills/<name>/SKILL.md`` and ``/uploads/<file>``, and
# copying those into code prefixes the container root — ``open()`` then raises
# FileNotFoundError. Nothing is lost, so the write-side wording ("DISCARDED") would
# be actively misleading here; hence a separate pattern and a separate notice.
_ABSOLUTE_PROVISIONED_RE = re.compile(r"""['"]/(?:skills|uploads)(?:/|['"])""")

ABSOLUTE_PATH_NOTICE = (
    "\n\n[SYSTEM NOTICE] Your code wrote file(s) to an ABSOLUTE path "
    "(/output/... or /scratch/...). Files written outside the current working "
    "directory are DISCARDED and were NOT delivered to the user. Re-run and write "
    "to the RELATIVE path with no leading slash, e.g. `output/report.pdf` for "
    "deliverables or `scratch/temp.png` for intermediate files. The working "
    "directory IS the workspace root, so the file tools' `/output/x` is simply "
    "`output/x` here."
)

ABSOLUTE_PROVISIONED_PATH_NOTICE = (
    "\n\n[SYSTEM NOTICE] Your code opened an ABSOLUTE workspace path "
    "(/skills/... or /uploads/...). Those leading-slash paths exist only in the FILE "
    "TOOLS' view; on this filesystem they live under the CURRENT WORKING DIRECTORY, "
    "so a leading slash sends open() to the container root and raises "
    "FileNotFoundError. Nothing was lost or discarded — the file simply was not "
    "read. Re-run with the same path minus the leading slash, e.g. "
    "`skills/<name>/SKILL.md` or `uploads/<file>`."
)

# Delivery zones of the executor working dir. ``output/`` is the ONLY zone the
# linsight harvester (``get_final_result_file``) treats as deliverables;
# ``scratch/`` is explicitly intermediate.
OUTPUT_DIR_NAME = "output"
SCRATCH_DIR_NAME = "scratch"


def path_namespace_rules(include_skills: bool = True) -> str:
    """The mapping between the two path namespaces the model is shown.

    The file tools (ls / read_file / write_file / edit_file) render every workspace
    path with a LEADING SLASH, while the interpreter's cwd IS that same workspace
    root — so `/output/a.md` and `output/a.md` are one file, and the model has to
    translate in both directions. Nothing said so until now, and a real run burned
    three model round-trips discovering it, then failed four `read_file` calls at the
    end by handing back a host path it had seen in the interpreter.

    ``include_skills`` is False for E2B: the sandbox copy-in snapshots the working dir
    BEFORE skills are materialised, so `skills/` genuinely is not there and promising
    it would just point the model at nothing.
    """
    zones = "`/output/x` is `output/x`, `/scratch/x` is `scratch/x`, `/uploads/x` is `uploads/x`"
    # Every example has to stay inside the zone set this executor actually has, or
    # the guidance points at something that is not there.
    read_example = "`open('/skills/...')`" if include_skills else "`open('/uploads/...')`"
    if include_skills:
        zones += ", `/skills/<name>/SKILL.md` is `skills/<name>/SKILL.md`"
    return (
        "WORKING DIRECTORY: your cwd IS the task workspace root. The file tools show "
        f"those same files with a LEADING SLASH: {zones}. "
        f"In code ALWAYS drop the leading slash — {read_example} or "
        "`open('/output/...')` resolves at the CONTAINER ROOT, so reads raise "
        "FileNotFoundError and writes are discarded and never delivered. Conversely, "
        "never hand a host path you saw here (e.g. `/root/.cache/.../output/a.png`) "
        "back to read_file — pass the workspace path `output/a.png`. Create the zone "
        "dirs before writing into them: `os.makedirs('output', exist_ok=True)`. "
    )


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
        """Corrective notice for absolute workspace paths in ``code``; "" if clean.

        Two independent failure modes, two notices, because the consequences differ:

        - WRITE side (``/output`` / ``/scratch``): the file lands outside the
          harvested working dir and silently vanishes from the result panel.
        - READ side (``/skills`` / ``/uploads``): ``open()`` raises FileNotFoundError
          and nothing is lost — telling the model its file was "DISCARDED" there
          would send it chasing a data-loss problem that never happened.

        Both hit at once → both notices, write side first. String-literal match only,
        which is specific enough that false positives are negligible, and the notice
        is non-blocking (appended to the tool result, never rejects the run).
        """
        if not code:
            return ""
        notices = ""
        if _ABSOLUTE_DELIVERABLE_RE.search(code):
            notices += ABSOLUTE_PATH_NOTICE
        if _ABSOLUTE_PROVISIONED_RE.search(code):
            notices += ABSOLUTE_PROVISIONED_PATH_NOTICE
        return notices

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
