import glob
import os
import re
import signal
import subprocess
import sys
import tempfile
from hashlib import md5
from pathlib import Path
from typing import Any

import matplotlib
from loguru import logger

from bisheng_langchain.gpts.tools.code_interpreter.base_executor import (
    OUTPUT_DIR_NAME,
    BaseExecutor,
    clip_middle,
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
            encoding="utf-8",
            errors="replace",
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

        # Clip BEFORE appending the advisory, same as the failure path above: the
        # advisory is the one instruction the model must act on next turn, so the
        # truncation must not be able to eat it. ``file_list`` is never clipped —
        # not seeing it is exactly what makes the model conclude nothing was written.
        logs_all = clip_middle(logs_all)
        # Deterministic safety net: if the script wrote a deliverable to an absolute
        # /output//scratch path it escaped the harvested working dir and silently
        # vanished (see base_executor). Append a corrective notice so the model
        # re-writes with a relative path on the next step. Non-blocking.
        advisory = self.absolute_path_advisory(original_code)
        if advisory:
            logs_all += advisory
        return {"exitcode": 0, "log": logs_all, "file_list": all_file_list}


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
