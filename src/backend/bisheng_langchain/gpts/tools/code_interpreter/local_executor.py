import glob
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
from hashlib import md5
from os import DirEntry
from pathlib import Path
from typing import Any

import matplotlib
from loguru import logger

from bisheng_langchain.gpts.tools.code_interpreter.base_executor import (
    OUTPUT_DIR_NAME,
    BaseExecutor,
    path_namespace_rules,
)

CODE_BLOCK_PATTERN = r"```(\w*)\n(.*?)\n```"
DEFAULT_TIMEOUT = 600
WIN32 = sys.platform == "win32"
PATH_SEPARATOR = (WIN32 and "\\") or "/"
WORKING_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "extensions")
# A bare "Timeout" reads as an infrastructure hiccup and invites a verbatim retry.
# Name the cause so the next attempt is narrower instead of identical.
TIMEOUT_MSG = (
    "Timeout: this script ran longer than {timeout}s and was killed. It did not finish, "
    "so nothing it was about to write exists. Scope the next attempt down — an unbounded "
    "loop, or a recursive scan rooted at / or another huge directory, cannot finish here."
)
UNKNOWN = "unknown"
# A failing run's log goes straight into the model's context. Cap it, keeping the
# TAIL: a traceback states its cause on the last lines.
MAX_FAILURE_LOG_CHARS = 8000
LOG_TRUNCATED_NOTICE = "[... earlier output truncated ...]\n"
PARTIAL_OUTPUT_HEADER = "\nOutput captured before the kill:\n"

LOCAL_DESCRIPTION = (
    """Evaluates python code in native environment. \
You must send the whole script every time and print your outputs. \
Script should be pure python code that can be evaluated. \
It should be in python format NOT markdown. \
The code should NOT be wrapped in backticks. \
FILE OUTPUT RULES (STRICT): write final deliverables to the RELATIVE directory \
`output/` (e.g. `output/report.pdf`) and intermediate files to `scratch/`; these \
are subfolders of the current working directory. NEVER use an absolute path with a \
leading slash such as `/output/...` or `/scratch/...` — anything written outside the \
current working directory is DISCARDED and will NOT be delivered to the user. \
"""
    + path_namespace_rules(include_skills=True)
    + """\
Do not use things like plot.show() as it will not work; save figures to `output/` \
instead. print() any output and results so you can capture the output. \
AVAILABLE LIBRARIES: this runs in the backend Python environment; these are ALREADY \
installed — pandas, numpy, matplotlib (charts), openpyxl / XlsxWriter (Excel), \
python-docx (Word), python-pptx (PowerPoint), Pillow (images), reportlab (generate PDF), and PyMuPDF a.k.a. \
`fitz` (read/parse PDF). To READ text or tables from a PDF, use `import fitz` \
(PyMuPDF); do NOT use pdfminer / pdfplumber / PyPDF2 — they are NOT installed. If an \
import fails, switch to an already-installed library instead of assuming a package \
exists; do NOT run `pip install` (this is a shared, offline environment)."""
)


class LocalExecutor(BaseExecutor):
    def __init__(self, minio: dict = None, **kwargs):
        super().__init__(minio, **kwargs)
        self.minio = minio

    @property
    def description(self) -> str:
        return LOCAL_DESCRIPTION

    @staticmethod
    def infer_lang(code):
        """infer the language for the code.
        TODO: make it robust.
        """
        if code.startswith("python ") or code.startswith("pip") or code.startswith("python3 "):
            return "sh"

        # check if code is a valid python code
        try:
            compile(code, "test", "exec")
            return "python"
        except SyntaxError:
            # not a valid python code
            return UNKNOWN

    @staticmethod
    def insert_set_font_code(code: str) -> str:
        """判断python代码中是否导入了matplotlib库，如果有则插入设置字体的代码"""

        split_code = code.split("\n")
        cache_file = matplotlib.get_cachedir()
        font_cache = glob.glob(f"{cache_file}/fontlist*")

        for cache in font_cache:
            os.remove(cache)

        # todo: 如果生成的代码中已经有了设置字体的代码，可能会导致该段代码失效
        if "matplotlib" in code:
            pattern = re.compile(r"(import matplotlib|from matplotlib)")
            index = max(i for i, line in enumerate(split_code) if pattern.search(line))
            split_code.insert(index + 1, 'import matplotlib\nmatplotlib.rc("font", family="WenQuanYi Zen Hei")')

        return "\n".join(split_code)

    @staticmethod
    def extract_code(
        text: str, pattern: str = CODE_BLOCK_PATTERN, detect_single_line_code: bool = False
    ) -> list[tuple[str, str]]:
        """Extract code from a text.

        Args:
            text (str): The text to extract code from.
            pattern (str, optional): The regular expression pattern for finding the
                code block. Defaults to CODE_BLOCK_PATTERN.
            detect_single_line_code (bool, optional): Enable the new feature for
                extracting single line code. Defaults to False.

        Returns:
            list: A list of tuples, each containing the language and the code.
              If there is no code block in the input text, the language would be "unknown".
              If there is code block but the language is not specified, the language would be "".
        """
        if not detect_single_line_code:
            match = re.findall(pattern, text, flags=re.DOTALL)
            return match if match else [(UNKNOWN, text)]

        # Extract both multi-line and single-line code block, separated by the | operator
        # `{3}(\w+)?\s*([\s\S]*?)`{3}: Matches multi-line code blocks.
        #    The (\w+)? matches the language, where the ? indicates it is optional.
        # `([^`]+)`: Matches inline code.
        code_pattern = re.compile(r"`{3}(\w+)?\s*([\s\S]*?)`{3}|`([^`]+)`")
        code_blocks = code_pattern.findall(text)

        # Extract the individual code blocks and languages from the matched groups
        extracted = []
        for lang, group1, group2 in code_blocks:
            if group1:
                extracted.append((lang.strip(), group1.strip()))
            elif group2:
                extracted.append(("", group2.strip()))

        return extracted

    @staticmethod
    def _cmd(lang):
        if lang.startswith("python") or lang in ["bash", "sh", "powershell"]:
            return lang
        if lang in ["shell"]:
            return "sh"
        if lang in ["ps1"]:
            return "powershell"
        raise NotImplementedError(f"{lang} not recognized in code execution")

    @staticmethod
    def _child_env(work_dir: str | None) -> dict[str, str]:
        """Environment for the executed script.

        ``HOME`` is pointed at the working directory. Otherwise ``expanduser('~')``
        resolves to the SERVICE account's home (``/root`` in the shipped image),
        which is shared by every user's runs and holds the download cache of their
        uploads — and reaching for ``~`` is exactly what a model does when it goes
        looking for "the file I was given". Paired with
        ``workspace_escape_guard``: the guard rejects the obvious spellings, this
        makes the ones it cannot see (``os.environ['HOME']``, a library resolving
        ``~`` internally) land inside the workspace instead of on the host.

        ``MPLCONFIGDIR`` is pinned to matplotlib's current cache dir FIRST, because
        moving ``HOME`` would otherwise send matplotlib to a fresh, empty config
        dir and make it rebuild the font cache on every single run.
        """
        env = os.environ.copy()
        if work_dir:
            env.setdefault("MPLCONFIGDIR", matplotlib.get_cachedir())
            env["HOME"] = work_dir
        return env

    @classmethod
    def _execute_code(
        cls,
        code: str | None = None,
        timeout: int | None = None,
        filename: str | None = None,
        work_dir: str | None = None,
        lang: str | None = "python",
        file_path: str | None = None,
    ):
        cmd = [
            sys.executable if lang.startswith("python") else cls._cmd(lang),
            f".\\{filename}" if WIN32 else filename,
        ]
        # start_new_session makes the child its own process group leader, so a timeout
        # can take down whatever it spawned as well (see _kill_process_tree).
        proc = subprocess.Popen(
            cmd,
            cwd=work_dir,
            env=cls._child_env(work_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=not WIN32,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # communicate() leaves the child alive on timeout — kill it, then reap the
            # pipes. The second communicate() returns everything buffered before the
            # kill, which is the only clue the model gets about where the script hung.
            cls._kill_process_tree(proc)
            stdout, stderr = proc.communicate()
            logger.warning("code interpreter run exceeded {}s and was killed", timeout)
            message = TIMEOUT_MSG.format(timeout=timeout)
            partial = f"{stdout or ''}{stderr or ''}"
            if not partial.strip():
                return 1, message, ""
            # Cap the partial output alone, never message+partial: _tail keeps the END
            # of what it is given, and the notice sits at the START — capping the pair
            # would drop the very line that explains the failure. _tail also prepends
            # its own truncation notice, which counts against the cap as well.
            budget = MAX_FAILURE_LOG_CHARS - len(message) - len(PARTIAL_OUTPUT_HEADER) - len(LOG_TRUNCATED_NOTICE)
            return 1, f"{message}{PARTIAL_OUTPUT_HEADER}{cls._tail(partial, budget)}", ""
        if proc.returncode:
            logs = stderr
            if file_path is not None:
                abs_path = str(Path(file_path).absolute())
                logs = logs.replace(str(abs_path), "").replace(filename, "")
            else:
                abs_path = str(Path(work_dir).absolute()) + PATH_SEPARATOR
                logs = logs.replace(str(abs_path), "")
        else:
            logs = stdout
        return proc.returncode, logs, ""

    @staticmethod
    def _kill_process_tree(proc: subprocess.Popen) -> None:
        """SIGKILL the run's whole process group, not just the direct child.

        The interpreter runs model-written code that routinely shells out (LibreOffice,
        pandoc, pip). Killing only ``proc`` leaves those grandchildren spinning, and a
        runaway one keeps a CPU core and a worker slot pinned for good.
        """
        if WIN32:
            proc.kill()
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            # already reaped, or start_new_session did not take — settle for the child
            proc.kill()

    @classmethod
    def execute_code(
        cls,
        code: str | None = None,
        timeout: int | None = None,
        filename: str | None = None,
        work_dir: str | None = None,
        lang: str | None = "python",
    ) -> tuple[int, str, str]:
        if all((code is None, filename is None)):
            error_msg = f"Either {code=} or {filename=} must be provided."
            logger.error(error_msg)
            raise AssertionError(error_msg)

        timeout = timeout or DEFAULT_TIMEOUT
        original_filename = filename

        if filename is None:
            code_hash = md5(code.encode()).hexdigest()
            # create a file with a automatically generated name
            filename = f"tmp_code_{code_hash}.{'py' if lang.startswith('python') else lang}"
        if work_dir is None:
            work_dir = WORKING_DIR
        filepath = os.path.join(work_dir, filename)
        file_dir = os.path.dirname(filepath)
        os.makedirs(file_dir, exist_ok=True)
        (Path(file_dir) / OUTPUT_DIR_NAME).mkdir(exist_ok=True, parents=True)
        if code is not None:
            with open(filepath, "w", encoding="utf-8") as fout:
                fout.write(code)
        try:
            return cls._execute_code(
                code=code, timeout=timeout, filename=filename, work_dir=work_dir, lang=lang, file_path=filepath
            )
        finally:
            if filepath is not None:
                os.remove(filepath)

    @staticmethod
    def _snapshot_files(dir_path: str) -> dict[str, tuple[float, int]]:
        """Map every non-hidden file under ``dir_path`` to ``(mtime, size)``.

        Taken before and after a run so the executor can tell what THIS run
        produced. Without the diff the working dir is indistinguishable from its
        contents: it also holds the prefetched uploaded sources and every earlier
        step's files, so "what did this code write" is otherwise unanswerable.
        """
        snapshot: dict[str, tuple[float, int]] = {}
        for root, dirs, files in os.walk(dir_path):
            # hidden dirs and __pycache__ are never deliverables or inputs
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for name in files:
                if name.startswith("."):
                    continue
                abs_path = os.path.join(root, name)
                try:
                    stat = os.stat(abs_path)
                except OSError:
                    # raced away between walk and stat — treat as absent
                    continue
                snapshot[os.path.relpath(abs_path, dir_path)] = (stat.st_mtime, stat.st_size)
        return snapshot

    def _relocate_root_files(self, dir_path: str, created: list[str]) -> list[tuple[str, str]]:
        """Move run-created ROOT-level files into ``output/``; return the moves.

        The working-dir root is not a delivery zone — only ``output/`` is harvested
        into the result panel — so a model that writes ``report.xlsx`` instead of
        ``output/report.xlsx`` loses its deliverable silently. Relocating is safe
        because only files *this run created* are eligible: prefetched upload
        sources and prior-step files sit in the pre-run snapshot and stay put.

        An existing ``output/<name>`` is overwritten on purpose: re-running the same
        script must refresh its deliverable, not accumulate ``report (1).xlsx``.
        """
        moved: list[tuple[str, str]] = []
        for rel in created:
            # anything with a path separator already lives in a zone (output/,
            # scratch/, or a model-made subdir) — leave it alone
            if os.sep in rel or "/" in rel:
                continue
            src = os.path.join(dir_path, rel)
            if not os.path.isfile(src):
                continue
            target_dir = os.path.join(dir_path, OUTPUT_DIR_NAME)
            dst = os.path.join(target_dir, rel)
            try:
                os.makedirs(target_dir, exist_ok=True)
                shutil.move(src, dst)
            except OSError:
                # best-effort: a file we cannot relocate stays where it is (it just
                # will not be delivered) — never fail the user's code run over this
                logger.exception("relocate root deliverable failed: {}", src)
                continue
            moved.append((rel, os.path.relpath(dst, dir_path)))
        return moved

    def run_with_dir(self, code: str, dir_path: str, lang: str) -> (int, str, list):
        """在指定目录下运行代码，并返回日志和生成的文件列表"""
        pre_snapshot = self._snapshot_files(dir_path)
        exitcode, logs, _ = self.execute_code(
            code,
            work_dir=dir_path,
            lang=lang,
        )
        file_list = []
        if exitcode != 0:
            return exitcode, logs, file_list

        post_snapshot = self._snapshot_files(dir_path)
        created = [rel for rel in post_snapshot if rel not in pre_snapshot]
        modified = [rel for rel, meta in post_snapshot.items() if rel in pre_snapshot and pre_snapshot[rel] != meta]

        # Root-level new files are in no delivery zone; normalise them into output/
        # and tell the model where they went (the old path stops resolving).
        moved = self._relocate_root_files(dir_path, created)
        relocated_from = {old for old, _ in moved}
        touched = [rel for rel in created if rel not in relocated_from]
        touched.extend(new for _, new in moved)
        touched.extend(modified)
        logs += self.relocation_advisory(moved)

        # 获取文件: only what this run actually produced. Uploading the whole
        # working dir every run (the previous behaviour) re-uploaded the prefetched
        # upload sources and every earlier step's output on each call, so the tool
        # result grew with the task and told the model nothing about its own write.
        for rel in touched:
            file_name = os.path.join(dir_path, rel)
            if not os.path.isfile(file_name):
                continue
            file_ext = os.path.splitext(rel)[-1]
            file_list.append(self.upload_minio(f"{uuid.uuid4().hex}.{file_ext}", file_name))
        # Mirror the same set into the session workspace so the file tools and the
        # next turn can see what this run produced (see sync_to_workspace).
        self.sync_to_workspace(dir_path, touched)
        # 同步执行结果文件到本地同步目录
        if self.local_sync_path and os.path.exists(self.local_sync_path):
            files_info = list(os.scandir(dir_path))
            self.sync_files_to_local(files_info, dir_path)
        return exitcode, logs, file_list

    @staticmethod
    def _tail(logs: str, limit: int = MAX_FAILURE_LOG_CHARS) -> str:
        """Keep the last ``limit`` characters of a failing run's log."""
        if len(logs) <= limit:
            return logs
        return LOG_TRUNCATED_NOTICE + logs[-limit:]

    def run(self, code: str) -> Any:
        original_code = code
        # Checked BEFORE anything executes: this executor is a subprocess on the
        # shared backend host, so by the time an escaping read has run, another
        # user's document is already in the model's context.
        escape_notice = self.workspace_escape_guard(original_code)
        if escape_notice:
            logger.warning("code interpreter: rejected a run that reaches outside the working directory")
            return {"exitcode": 1, "log": escape_notice, "file_list": []}
        code_blocks = self.extract_code(code)
        logs_all = ""
        all_file_list = []
        for i, code_block in enumerate(code_blocks):
            lang, code = code_block
            lang = self.infer_lang(code)
            code = self.insert_set_font_code(code)
            if self.local_sync_path and os.path.exists(self.local_sync_path):
                exit_code, logs, file_list = self.run_with_dir(code, dir_path=self.local_sync_path, lang=lang)
            else:
                with tempfile.TemporaryDirectory() as temp_dir:
                    exit_code, logs, file_list = self.run_with_dir(code, dir_path=temp_dir, lang=lang)
            logs_all += "\n" + logs
            if exit_code != 0:
                # The traceback (or the timeout notice) lives in THIS block's log, so it
                # has to be accumulated BEFORE the early return. Returning the not-yet
                # accumulated prefix handed the model {"exitcode": 1, "log": ""} on every
                # failure and forced it to debug blind.
                logger.warning("code interpreter block {}/{} exited {}", i + 1, len(code_blocks), exit_code)
                # The advisory has to be attached HERE too, not only on the success
                # path below: reading an absolute `/skills/...` raises
                # FileNotFoundError, which is exactly a non-zero exit — so the one
                # failure the read-side notice exists to explain would otherwise
                # never see it. Appended AFTER ``_tail`` (which keeps the tail) so
                # the truncation cannot eat it.
                return {"exitcode": exit_code, "log": self._tail(logs_all) + self.absolute_path_advisory(original_code)}
            all_file_list += file_list

        # Deterministic safety net: if the script wrote a deliverable to an absolute
        # /output//scratch path it escaped the harvested working dir and silently
        # vanished (see base_executor). Append a corrective notice so the model
        # re-writes with a relative path on the next step. Non-blocking.
        advisory = self.absolute_path_advisory(original_code)
        if advisory:
            logs_all += advisory
        return {"exitcode": 0, "log": logs_all, "file_list": all_file_list}

    def sync_files_to_local(self, files_info: list[DirEntry], root_path: str):
        if not files_info:
            return
        for file in files_info:
            # ignore hidden files
            if file.name.startswith("."):
                continue
            if file.is_file():
                self.download_file(file, root_path)
            else:
                new_files_info = os.scandir(file.path)
                self.sync_files_to_local(list(new_files_info), root_path)

    def download_file(self, file_info: DirEntry, root_path: str):
        relative_path = file_info.path.replace(root_path, "").lstrip(os.sep)
        local_path = os.path.join(self.local_sync_path, relative_path)
        local_dir = os.path.dirname(local_path)
        os.makedirs(local_dir, exist_ok=True)
        shutil.move(file_info.path, local_path)


if __name__ == "__main__":
    tmp_executor = LocalExecutor(
        minio={},
    )
    result = tmp_executor.run(
        code="""import os\nwith open("output/test2.txt", "w") as f:\n    f.write("Hello, E2222B!")\nprint("File written to output/test.txt")"""
    )
    result2 = tmp_executor.run(
        code="""import os\nwith open("output/test2.txt", "r") as f:\n    content = f.read()\n    print(f"File read from output/test2.txt=={content}")"""
    )
    print(result)
    print(result2)
