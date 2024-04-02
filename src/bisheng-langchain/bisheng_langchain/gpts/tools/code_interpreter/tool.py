import itertools
import os
import pathlib
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from hashlib import md5
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Type

try:
    from termcolor import colored
except ImportError:

    def colored(x, *args, **kwargs):
        return x


from autogen.code_utils import extract_code, infer_lang
from langchain_community.tools import Tool
from langchain_core.pydantic_v1 import BaseModel, Field
from loguru import logger

DEFAULT_TIMEOUT = 600
WIN32 = sys.platform == "win32"
PATH_SEPARATOR = WIN32 and "\\" or "/"
WORKING_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "extensions")
TIMEOUT_MSG = "Timeout"


def _cmd(lang):
    if lang.startswith("python") or lang in ["bash", "sh", "powershell"]:
        return lang
    if lang in ["shell"]:
        return "sh"
    if lang in ["ps1"]:
        return "powershell"
    raise NotImplementedError(f"{lang} not recognized in code execution")


def execute_code(
    code: Optional[str] = None,
    timeout: Optional[int] = None,
    filename: Optional[str] = None,
    work_dir: Optional[str] = None,
    lang: Optional[str] = "python",
) -> Tuple[int, str, str]:
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
    (Path(file_dir) / 'output').mkdir(exist_ok=True, parents=True)
    if code is not None:
        with open(filepath, "w", encoding="utf-8") as fout:
            fout.write(code)

    cmd = [
        sys.executable if lang.startswith("python") else _cmd(lang),
        f".\\{filename}" if WIN32 else filename,
    ]
    if WIN32:
        logger.warning("SIGALRM is not supported on Windows. No timeout will be enforced.")
        result = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
        )
    else:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                subprocess.run,
                cmd,
                cwd=work_dir,
                capture_output=True,
                text=True,
            )
            try:
                result = future.result(timeout=timeout)
            except TimeoutError:
                if original_filename is None:
                    os.remove(filepath)
                return 1, TIMEOUT_MSG, None
    if original_filename is None:
        os.remove(filepath)
    if result.returncode:
        logs = result.stderr
        if original_filename is None:
            abs_path = str(pathlib.Path(filepath).absolute())
            logs = logs.replace(str(abs_path), "").replace(filename, "")
        else:
            abs_path = str(pathlib.Path(work_dir).absolute()) + PATH_SEPARATOR
            logs = logs.replace(str(abs_path), "")
    else:
        logs = result.stdout
    return result.returncode, logs, None


def head_file(path: str, n: int) -> List[str]:
    """Get the first n lines of a file."""
    try:
        with open(path, "r") as f:
            return [str(line) for line in itertools.islice(f, n)]
    except Exception:
        return []


class CodeInterpreterToolArguments(BaseModel):
    """Arguments for the BearlyInterpreterTool."""

    python_code: str = Field(
        ...,
        example="print('Hello World')",
        description=(
            "The pure python script to be evaluated. "
            "The contents will be in main.py. "
            "It should not be in markdown format."
        ),
    )


base_description = """Evaluates python code in native environment. \
You must send the whole script every time and print your outputs. \
Script should be pure python code that can be evaluated. \
It should be in python format NOT markdown. \
The code should NOT be wrapped in backticks. \
If you have any files outputted write them to "output/" relative to the execution \
path. Output can only be read from the directory, stdout, and stdin. \
Do not use things like plot.show() as it will \
not work instead write them out `output/`\
print() any output and results so you can capture the output."""  # noqa: T201


class FileInfo(BaseModel):
    """Information about a file to be uploaded."""

    source_path: str
    description: str


class CodeInterpreterTool:
    """Tool for evaluating python code in native environment."""

    name = "code_interpreter"
    args_schema: Type[BaseModel] = CodeInterpreterToolArguments
    files: Dict[str, FileInfo] = {}

    @property
    def file_description(self) -> str:
        if not isinstance(self.files, dict):
            return ""
        lines = ["The following files available in the evaluation environment:"]
        for source_path, file_info in self.files.items():
            peek_content = head_file(file_info.source_path, 4)
            lines.append(
                f"- path: `{file_info.source_path}` \n first four lines: {peek_content}"
                f" \n description: `{file_info.description}`"
            )
        return "\n".join(lines)

    @property
    def description(self) -> str:
        return (base_description + "\n\n" + self.file_description).strip()

    def _run(self, code_string: str) -> dict:
        code_blocks = extract_code(code_string)
        logs_all = ''
        for i, code_block in enumerate(code_blocks):
            lang, code = code_block
            lang = infer_lang(code)
            exitcode, logs, _ = execute_code(code, lang=lang)
            logs_all += "\n" + logs
            if exitcode != 0:
                return {'exitcode': exitcode, 'log': logs_all}

        return {'exitcode': 0, 'log': logs_all, 'pic_list': []}

    def as_tool(self) -> Tool:
        return Tool.from_function(
            func=self._run,
            name=self.name,
            description=self.description,
            args_schema=self.args_schema,
        )


if __name__ == '__main__':
    code_string = """print('hha')"""
    code_blocks = extract_code(code_string)
    logger.info(code_blocks)
    logs_all = ''
    for i, code_block in enumerate(code_blocks):
        lang, code = code_block
        lang = infer_lang(code)
        print(
            colored(
                f"\n>>>>>>>> EXECUTING CODE BLOCK {i} (inferred language is {lang})...",
                "red",
            ),
            flush=True,
        )
        exitcode, logs, image = execute_code(code, lang=lang)
        logs_all += "\n" + logs
        if exitcode != 0:
            logger.error(f'{exitcode}, {logs_all}')

    logger.info(logs_all)
