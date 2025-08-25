import base64
import os
import tempfile
import uuid
from typing import List

from e2b.sandbox.filesystem.filesystem import WriteEntry
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
            self.sandbox = Sandbox(domain=domain, api_key=api_key, timeout=timeout)
            if self.file_list:
                self.sandbox.files.write(self.file_list)

    @property
    def description(self) -> str:
        return "A code interpreter that can execute python code. Input should be a valid python code."

    def run(self, code: str):
        """
        Execute code in the E2B Code Interpreter sandbox.
        :param code: The code to execute.
        :return: The result of the code execution.
        """
        if self.keep_sandbox:
            return self.run_code_with_one_sandbox(code)
        sandbox = None
        try:
            sandbox = Sandbox(domain=self.domain, api_key=self.api_key, timeout=self.timeout)
            if self.file_list:
                sandbox.files.write(self.file_list)
            execution = sandbox.run_code(code)
            results, file_list = self.parse_results(execution.results)
            return {
                "results": results,
                "stdout": execution.logs.stdout,
                "stderr": execution.logs.stderr,
                "error": execution.error,
                "file_list": file_list,
            }
        finally:
            if sandbox:
                sandbox.kill()

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
        return parsed_results, file_list

    def close(self):
        if self.sandbox:
            self.sandbox.kill()


if __name__ == '__main__':
    e2b_api_key = os.environ.get("E2B_API_KEY")
    e2b_exec = E2bCodeExecutor(api_key=e2b_api_key, keep_sandbox=True)
    result = e2b_exec.run(code="""print("hello world123")""")
    print(result)
    print(E2bCodeExecutor.parse_results(result['results']))
    print(11111)
    e2b_exec.close()

    # boxes = Sandbox.list(api_key=e2b_api_key)
    # for box in boxes:
    #     Sandbox.kill(sandbox_id=box.sandbox_id, api_key=e2b_api_key)
