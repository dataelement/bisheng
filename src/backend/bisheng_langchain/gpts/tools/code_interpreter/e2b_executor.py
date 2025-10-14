import base64
import os
import tempfile
import uuid
from typing import List

from e2b.sandbox.filesystem.filesystem import WriteEntry, EntryInfo, FileType
from e2b_code_interpreter import Sandbox, Result

from bisheng_langchain.gpts.tools.code_interpreter.base_executor import BaseExecutor


class E2bCodeExecutor(BaseExecutor):

    def __init__(self, minio: dict, api_key: str, domain: str = None, timeout: int = 300,
                 file_list: list[WriteEntry] = None, keep_sandbox: bool = False, **kwargs):
        """
            timeout: Create sandbox with and keep it running for 300 seconds
        """
        super().__init__(minio, **kwargs)
        self.minio = minio
        self.api_key = api_key
        self.domain = domain
        self.timeout = timeout
        self.file_list = file_list
        self.keep_sandbox = keep_sandbox  # 是否保持一个sandbox, 默认只有在执行的时候才创建一个沙盒
        self.sandbox_file_cache = {}  # 缓存已经下载过的文件，避免重复下载

        if self.file_list:
            new_file_list = []
            for one in self.file_list:
                with open(one.data, 'rb') as f:
                    new_file_list.append({
                        "path": one.path,
                        "data": f.read()
                    })
            self.file_list = new_file_list

        self.sandbox = None
        if self.keep_sandbox:
            self.init_sandbox()

    @property
    def description(self) -> str:
        return "A code interpreter that can execute python code. Input should be a valid python code. If you have any files outputted write them to `output/` relative to the execution path."

    def init_sandbox(self):
        if not self.sandbox:
            self.sandbox = Sandbox(domain=self.domain, api_key=self.api_key, timeout=self.timeout)
            self.sandbox.files.make_dir("output")  # 确保output目录存在
            if self.file_list:
                self.sandbox.files.write(self.file_list)
                # 初始化缓存信息
                files_info = self.sandbox.files.list("./")
                for file in files_info:
                    self.sandbox_file_cache[file.path] = file

    def run(self, code: str):
        """
        Execute code in the E2B Code Interpreter sandbox.
        :param code: The code to execute.
        :return: The result of the code execution.
        """
        # need to keep the sandbox, then reuse the existing one and do not close it
        if self.keep_sandbox:
            return self.run_code_with_one_sandbox(code)

        self.init_sandbox()
        try:
            execution = self.sandbox.run_code(code)
            results, file_list = self.parse_results(execution.results)
            return {
                "results": results,
                "stdout": execution.logs.stdout,
                "stderr": execution.logs.stderr,
                "error": execution.error,
                "file_list": file_list,
            }
        finally:
            self.close()

    def run_code_with_one_sandbox(self, code: str) -> dict:
        """
        Execute code in the E2B Code Interpreter sandbox.
        :param code: The code to execute.
        :return: The result of the dict.
        """
        if self.sandbox is None:
            raise RuntimeError('Sandbox is destroyed.')
        execution = self.sandbox.run_code(code)
        results, file_list = self.parse_results(execution.results)
        return {
            "results": results,
            "stdout": execution.logs.stdout,
            "stderr": execution.logs.stderr,
            "error": execution.error,
            "file_list": file_list,
        }

    def parse_results(self, results: List[Result]):
        """
        Parse the results from the E2B Code Interpreter.
        :param results: The results from the code execution.
        :return: Parsed results.
        """
        parsed_results = []
        file_list = []
        for result in results:
            if result.text:
                parsed_results.append({"text": result.text})
            if result.html:
                parsed_results.append({"html": result.html})
            if result.markdown:
                parsed_results.append({"markdown": result.markdown})
            if result.svg:
                parsed_results.append({"svg": result.svg})
            if result.png:
                tmp_dir = tempfile.gettempdir()
                file_path = os.path.join(tmp_dir, uuid.uuid4().hex + ".png")
                with open(file_path, "wb") as f:
                    f.write(base64.b64decode(result.png))
                file_list.append(self.upload_minio(f"{uuid.uuid4().hex}.png", file_path))
            if result.jpeg:
                tmp_dir = tempfile.gettempdir()
                file_path = os.path.join(tmp_dir, uuid.uuid4().hex + ".jpeg")
                with open(file_path, "wb") as f:
                    f.write(base64.b64decode(result.jpeg))
                file_list.append(self.upload_minio(f"{uuid.uuid4().hex}.jpeg", file_path))
            if result.json:
                parsed_results.append({"json": result.json})
            if result.data:
                parsed_results.append({"data": result.data})
        if self.local_sync_path and os.path.exists(self.local_sync_path) and self.sandbox:
            # 将沙盒中的文件同步到本地目录
            files_info = self.sandbox.files.list("./")
            self.sync_files_to_local(files_info)

        return parsed_results, file_list

    def sync_files_to_local(self, files_info: List[EntryInfo]):
        if not files_info:
            return
        for file in files_info:
            # ignore hidden files
            if file.name.startswith("."):
                continue
            if file.type == FileType.FILE:
                if file.path not in self.sandbox_file_cache:
                    self.sandbox_file_cache[file.path] = file
                    self.download_file(file)
                # only download modified files
                if self.sandbox_file_cache[file.path].modified_time < file.modified_time:
                    self.download_file(file)
            else:
                new_files_info = self.sandbox.files.list(file.path)
                self.sync_files_to_local(new_files_info)

    def download_file(self, file_info: EntryInfo):
        relative_path = file_info.path.replace("/home/user/", "")
        local_path = os.path.join(self.local_sync_path, relative_path)
        local_dir = os.path.dirname(local_path)
        os.makedirs(local_dir, exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(self.sandbox.files.read(file_info.path, format="bytes"))

    def close(self):
        if self.sandbox:
            self.sandbox.kill()
            self.sandbox = None


if __name__ == '__main__':
    e2b_api_key = os.environ.get("E2B_API_KEY")
    e2b_exec = E2bCodeExecutor(api_key=e2b_api_key, keep_sandbox=True, minio={}, local_sync_path="./e2b_output")
    result = e2b_exec.run(
        code="""import requests\nimport os
os.makedirs('./downloaded_wallpapers', exist_ok=True)
# 选定一个新的可靠高清风景图片链接
direct_image_url = 'https://images.unsplash.com/photo-1524758631624-e2822e304c36?ixid=MnwxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8&ixlib=rb-1.2.1&auto=format&fit=crop&w=1050&q=80'
output_path = './downloaded_wallpapers/wallpaper_1.jpg'
try:
    response = requests.get(direct_image_url, stream=True)
    if response.status_code == 200:
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
        print(f'壁纸已成功下载到 {output_path}')
    else:
        print(f'请求失败，状态码: {response.status_code}')
except Exception as e:
    print(f'发生异常: {str(e)}')""")
    print(result)
    print(11111)
    e2b_exec.close()

    # boxes = Sandbox.list(api_key=e2b_api_key)
    # for box in boxes:
    #     Sandbox.kill(sandbox_id=box.sandbox_id, api_key=e2b_api_key)
