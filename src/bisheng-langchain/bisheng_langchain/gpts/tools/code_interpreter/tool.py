import glob
import itertools
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from hashlib import md5
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Type
from uuid import uuid4

import matplotlib
from langchain_community.tools import Tool
from langchain_core.pydantic_v1 import BaseModel, Field
from loguru import logger

CODE_BLOCK_PATTERN = r"```(\w*)\n(.*?)\n```"
DEFAULT_TIMEOUT = 600
WIN32 = sys.platform == 'win32'
PATH_SEPARATOR = WIN32 and '\\' or '/'
WORKING_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'extensions')
TIMEOUT_MSG = 'Timeout'
UNKNOWN = "unknown"


def _cmd(lang):
    if lang.startswith('python') or lang in ['bash', 'sh', 'powershell']:
        return lang
    if lang in ['shell']:
        return 'sh'
    if lang in ['ps1']:
        return 'powershell'
    raise NotImplementedError(f'{lang} not recognized in code execution')


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


def extract_code(
    text: str, pattern: str = CODE_BLOCK_PATTERN, detect_single_line_code: bool = False
) -> List[Tuple[str, str]]:
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


def execute_code(
    code: Optional[str] = None,
    timeout: Optional[int] = None,
    filename: Optional[str] = None,
    work_dir: Optional[str] = None,
    lang: Optional[str] = 'python',
) -> Tuple[int, str, str]:
    if all((code is None, filename is None)):
        error_msg = f'Either {code=} or {filename=} must be provided.'
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
        with open(filepath, 'w', encoding='utf-8') as fout:
            fout.write(code)

    cmd = [
        sys.executable if lang.startswith('python') else _cmd(lang),
        f'.\\{filename}' if WIN32 else filename,
    ]
    if WIN32:
        logger.warning('SIGALRM is not supported on Windows. No timeout will be enforced.')
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
            logs = logs.replace(str(abs_path), '').replace(filename, '')
        else:
            abs_path = str(pathlib.Path(work_dir).absolute()) + PATH_SEPARATOR
            logs = logs.replace(str(abs_path), '')
    else:
        logs = result.stdout
    return result.returncode, logs, None


def head_file(path: str, n: int) -> List[str]:
    """Get the first n lines of a file."""
    try:
        with open(path, 'r') as f:
            return [str(line) for line in itertools.islice(f, n)]
    except Exception:
        return []


def upload_minio(
    param: dict,
    bucket: str,
    object_name: str,
    file_path,
    content_type='application/text',
):
    # 初始化minio
    import minio

    minio_client = minio.Minio(
        endpoint=param.get('MINIO_ENDPOINT'),
        access_key=param.get('MINIO_ACCESS_KEY'),
        secret_key=param.get('MINIO_SECRET_KEY'),
        secure=param.get('SCHEMA'),
        cert_check=param.get('CERT_CHECK'),
    )
    minio_share = minio.Minio(
        endpoint=param.get('MINIO_SHAREPOIN'),
        access_key=param.get('MINIO_ACCESS_KEY'),
        secret_key=param.get('MINIO_SECRET_KEY'),
        secure=param.get('SCHEMA'),
        cert_check=param.get('CERT_CHECK'),
    )
    logger.debug(
        'upload_file obj={} bucket={} file_paht={}',
        object_name,
        bucket,
        file_path,
    )
    minio_client.fput_object(
        bucket_name=bucket,
        object_name=object_name,
        file_path=file_path,
        content_type=content_type,
    )
    return minio_share.presigned_get_object(
        bucket_name=bucket,
        object_name=object_name,
        expires=timedelta(days=7),
    )


def insert_set_font_code(code: str) -> str:
    """判断python代码中是否导入了matplotlib库，如果有则插入设置字体的代码"""

    split_code = code.split('\n')
    cache_file = matplotlib.get_cachedir()
    font_cache = glob.glob(f'{cache_file}/fontlist*')

    for cache in font_cache:
        os.remove(cache)

    # todo: 如果生成的代码中已经有了设置字体的代码，可能会导致该段代码失效
    if 'matplotlib' in code:
        pattern = re.compile(r'(import matplotlib|from matplotlib)')
        index = max(i for i, line in enumerate(split_code) if pattern.search(line))
        split_code.insert(index + 1, 'import matplotlib\nmatplotlib.rc("font", family="WenQuanYi Zen Hei")')

    return '\n'.join(split_code)


class CodeInterpreterToolArguments(BaseModel):
    """Arguments for the BearlyInterpreterTool."""

    python_code: str = Field(
        ...,
        example="print('Hello World')",
        description=(
            'The pure python script to be evaluated. '
            'The contents will be in main.py. '
            'It should not be in markdown format.'
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

    name = 'bisheng_code_interpreter'
    args_schema: Type[BaseModel] = CodeInterpreterToolArguments

    def __init__(
        self,
        minio: Dict[str, any],
        files: Dict[str, FileInfo] = None,
    ) -> None:
        self.minio = minio
        self.files = files if files else {}

    @property
    def file_description(self) -> str:
        if not len(self.files) or not isinstance(self.files, dict):
            return ''
        lines = ['The following files available in the evaluation environment:']
        for source_path, file_info in self.files.items():
            peek_content = head_file(file_info.source_path, 4)
            lines.append(
                f'- path: `{file_info.source_path}` \n first four lines: {peek_content}'
                f' \n description: `{file_info.description}`'
            )
        return '\n'.join(lines)

    @property
    def description(self) -> str:
        return (base_description + '\n\n' + self.file_description).strip()

    def _run(self, code_string: str) -> dict:
        code_blocks = extract_code(code_string)
        logs_all = ''
        file_list = []
        for i, code_block in enumerate(code_blocks):
            lang, code = code_block
            lang = infer_lang(code)
            code = insert_set_font_code(code)
            temp_dir = tempfile.TemporaryDirectory()
            exitcode, logs, _ = execute_code(
                code,
                work_dir=temp_dir.name,
                lang=lang,
            )
            logs_all += '\n' + logs
            if exitcode != 0:
                return {'exitcode': exitcode, 'log': logs_all}

            # 获取文件
            temp_output_dir = Path(temp_dir.name)
            for root, dirs, files in os.walk(temp_output_dir):
                for name in files:
                    file_name = os.path.join(root, name)
                    if self.minio:
                        file_type = file_name.rsplit('.', 1)[-1]
                        object_name = uuid4().hex
                        file_list.append(upload_minio(self.minio, 'bisheng', f'{object_name}.{file_type}', file_name))
                    else:
                        file_list.append(file_name)
            temp_dir.cleanup()

        return {'exitcode': 0, 'log': logs_all, 'file_list': file_list}

    def as_tool(self) -> Tool:
        return Tool.from_function(
            func=self._run,
            name=self.name,
            description=self.description,
            args_schema=self.args_schema,
        )
