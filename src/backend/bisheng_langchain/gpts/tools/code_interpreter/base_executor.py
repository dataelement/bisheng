import os
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

# --- Workspace escape ------------------------------------------------------
# The local executor is a subprocess on the SHARED backend host, not a sandbox:
# a script can read anything the service account can. That is how a daily-chat
# turn once answered from `/root/.cache/bisheng/bisheng/` — the global download
# cache, where EVERY user's uploads pile up under a flat sha256 name. Reading
# another tenant's document is not a feature we want to keep, so these patterns
# reject the run outright (unlike the advisories above, which only annotate).
#
# Matching an ACCESS VERB rather than a bare string literal is deliberate: code
# may legitimately mention such a path in prose it prints back to the user.
_FS_ACCESS_VERBS = (
    "open|walk|scandir|listdir|glob|iglob|rglob|Path|PosixPath|copy|copy2|copyfile|copytree|"
    "move|rename|remove|unlink|rmtree|stat|lstat|getsize|exists|isfile|isdir|read_text|read_bytes"
)
# Host directories that are never part of a workspace. The workspace's own
# absolute-looking zones (/output /scratch /skills /uploads) are handled by
# ``absolute_path_advisory`` and are deliberately absent here.
_HOST_ROOTS = "root|home|etc|proc|sys|boot|opt|srv|usr|var|app|data|mnt|media"
# Group 2 captures the whole literal so the caller can tell "somewhere on the
# host" from "my own working dir, spelled absolutely" — linsight hands the model
# host paths of its own workspace, so those must stay legal.
_HOST_PATH_ACCESS_RE = re.compile(
    rf"""\b(?:{_FS_ACCESS_VERBS})\s*\([^)\n]{{0,120}}?(['"])(/(?:{_HOST_ROOTS})[^'"\n]*)\1"""
)
# ``expanduser("~")`` / ``Path.home()`` resolve to the SERVICE account's home.
# A model hunting for "the file I was given" reaches for ``~`` early.
_HOME_EXPANSION_RE = re.compile(r"""expanduser\s*\(\s*['"]~|Path\s*\.\s*home\s*\(""")
# A scan rooted at ``/`` walks the entire container.
_ROOT_SCAN_RE = re.compile(r"""\b(?:walk|glob|iglob|scandir|listdir)\s*\(\s*['"]/['"]""")

WORKSPACE_ESCAPE_NOTICE = (
    "[SYSTEM NOTICE] This run was REJECTED and nothing was executed: the code reaches OUTSIDE "
    "the working directory — a host path (/root, /etc, /app, /home, ...), the expanded home "
    "directory (`~`), or a scan rooted at `/`. Those locations are shared infrastructure that "
    "may hold other users' data; they are not yours to read.\n"
    "Your current working directory IS your workspace. Use RELATIVE paths only: "
    "`uploads/<file>` for provided sources, `output/<file>` for deliverables, `scratch/<file>` "
    "for intermediates.\n"
    "If what you are looking for is not under the working directory, it was NOT provided to you "
    "on this turn. Say so plainly and ask for it — do not search the filesystem for it, and do "
    "not answer from memory of an earlier turn as if you had re-read the file."
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
        # Object-storage prefix of the session workspace (``workspace/<svid>``).
        # Set by the linsight tool binder; empty for every other caller, which
        # simply disables the mirror in ``sync_to_workspace``.
        self.workspace_prefix = kwargs.get("workspace_prefix", None)

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

    def workspace_escape_guard(self, code: str) -> str:
        """Rejection notice when ``code`` reaches outside the working dir; "" if clean.

        Unlike ``absolute_path_advisory`` (annotates a completed run), a hit here
        means the run must NOT happen: the local executor shares a filesystem with
        the backend service, so a read of ``/root/.cache/...`` returns other users'
        uploaded documents. Blocking after the fact would be pointless — the data
        would already be in the model's context.

        Two deliberate exemptions keep legitimate code running:

        - Matching is VERB-anchored, so prose stays legal: a script may print
          "nothing under /root/.cache" without being rejected; only an actual
          ``open`` / ``os.walk`` / ``glob`` against a host root trips it.
        - A literal under ``local_sync_path`` is this run's OWN workspace written
          absolutely. ``path_namespace_rules`` shows the model exactly such host
          paths, so rejecting them would break the thing we told it to expect.
        """
        if not code:
            return ""
        work_dir = (self.local_sync_path or "").rstrip("/")
        for match in _HOST_PATH_ACCESS_RE.finditer(code):
            path = match.group(2)
            if work_dir and (path == work_dir or path.startswith(f"{work_dir}/")):
                continue
            return WORKSPACE_ESCAPE_NOTICE
        # `~` and `/` are never the workspace, so no exemption applies.
        if _HOME_EXPANSION_RE.search(code) or _ROOT_SCAN_RE.search(code):
            return WORKSPACE_ESCAPE_NOTICE
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

    def sync_to_workspace(self, dir_path: str, rel_paths: list[str]) -> int:
        """Mirror this run's files into the session workspace prefix. Returns the count.

        The executor writes to a LOCAL working dir that is deleted when the task
        ends (``_cleanup_resources``), while ``workspace/<svid>/`` in object storage
        is what the file tools (``ls`` / ``read_file``) actually see and what the
        next turn inherits via ``seed_workspace_from_previous``. Without this
        mirror a code-generated deliverable exists ONLY on that local disk, which
        produced two long-standing defects:

          * the model cannot ``ls`` the file it just wrote (the prompt had to carry
            an explicit "trust exitcode 0, do not go looking for it" caveat);
          * a follow-up turn runs under a fresh svid whose workspace seeds from the
            previous one's ``output/`` — empty, because nothing was ever written
            there — so "把封面加个副标题" finds no deck and can only regenerate.

        Deletions are deliberately NOT mirrored: this runs off a created/modified
        diff, and reconciling removals would mean trusting a partially-failed run
        to delete objects the harvester may still need.

        Best-effort by design — a mirror failure must never fail the run. The local
        copy is still what ``get_final_result_file`` harvests, so the user gets the
        deliverable either way.
        """
        if not self.minio or not self.workspace_prefix or not rel_paths:
            return 0

        bucket = self.minio.get("public_bucket") or "bisheng"
        prefix = self.workspace_prefix.strip("/")
        try:
            minio_client = self._minio_client()
        except Exception:
            logger.exception("workspace mirror: minio client init failed; local copy is unaffected")
            return 0

        synced = 0
        for rel in rel_paths:
            # Normalise once: a leading slash would make os.path.join return the
            # absolute path and silently skip the file.
            rel_key = rel.replace(os.sep, "/").lstrip("/")
            local_path = os.path.join(dir_path, rel_key)
            if not os.path.isfile(local_path):
                continue
            object_name = f"{prefix}/{rel_key}"
            try:
                minio_client.fput_object(bucket_name=bucket, object_name=object_name, file_path=local_path)
                synced += 1
            except Exception:
                # One unmirrored file degrades ls/continuity for that file only.
                logger.exception("workspace mirror failed for {}", object_name)
        if synced:
            logger.debug("workspace mirror: {} file(s) -> {}/{}", synced, bucket, prefix)
        return synced

    def _minio_client(self) -> Minio:
        return Minio(
            endpoint=self.minio.get("endpoint"),
            access_key=self.minio.get("access_key"),
            secret_key=self.minio.get("secret_key"),
            secure=self.minio.get("schema") or self.minio.get("secure"),
            cert_check=self.minio.get("cert_check"),
        )

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
